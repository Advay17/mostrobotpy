# validated: 2017-12-09 EN f9bece2ffbf7 edu/wpi/first/wpilibj/Ultrasonic.java
#----------------------------------------------------------------------------
# Copyright (c) FIRST 2008-2012. All Rights Reserved.
# Open Source Software - may be modified and shared by FRC teams. The code
# must be accompanied by the FIRST BSD license file in the root directory of
# the project.
#----------------------------------------------------------------------------

import hal
import threading
import weakref

from .counter import Counter
from .interfaces import PIDSource
from .livewindow import LiveWindow
from .resource import Resource
from .sensorbase import SensorBase
from .timer import Timer

__all__ = ["Ultrasonic"]

class Ultrasonic(SensorBase):
    """Ultrasonic rangefinder control
    
    The Ultrasonic rangefinder measures
    absolute distance based on the round-trip time of a ping generated by
    the controller.  These sensors use two transducers, a speaker and a
    microphone both tuned to the ultrasonic range. A common ultrasonic
    sensor, the Daventech SRF04 requires a short pulse to be generated on
    a digital channel. This causes the chirp to be emitted. A second line
    becomes high as the ping is transmitted and goes low when the echo is
    received. The time that the line is high determines the round trip
    distance (time of flight).
    
    .. not_implemented: initialize
    """

    class Unit:
        """The units to return when PIDGet is called"""
        kInches = 0
        kMillimeters = 1

    #: Time (sec) for the ping trigger pulse.
    kPingTime = 10 * 1e-6
    
    #: Priority that the ultrasonic round robin task runs.
    kPriority = 90
    
    #: Max time (ms) between readings.
    kMaxUltrasonicTime = 0.1
    kSpeedOfSoundInchesPerSec = 1130.0 * 12.0
    
    PIDSourceType = PIDSource.PIDSourceType

    _static_mutex = threading.RLock()
    
    #: ultrasonic sensor list
    sensors = weakref.WeakSet()
    
    #: Automatic round robin mode
    automaticEnabled = False
    instances = 0
    _thread = None

    @staticmethod
    def isAutomaticMode():
        with Ultrasonic._static_mutex:
            return Ultrasonic.automaticEnabled

    @staticmethod
    def ultrasonicChecker():
        """Background task that goes through the list of ultrasonic sensors
        and pings each one in turn. The counter is configured to read the
        timing of the returned echo pulse.

        .. warning:: DANGER WILL ROBINSON, DANGER WILL ROBINSON: This code runs
            as a task and assumes that none of the ultrasonic sensors will
            change while it's running. If one does, then this will certainly
            break. Make sure to disable automatic mode before changing
            anything with the sensors!!
        """
        while Ultrasonic.isAutomaticMode():
            count = 0
            for u in Ultrasonic.sensors:
                if not Ultrasonic.isAutomaticMode():
                    return
                if u is None:
                    continue
                count += 1
                if u.isEnabled():
                    # do the ping
                    u.pingChannel.pulse(Ultrasonic.kPingTime)
                Timer.delay(.1) # wait for ping to return
            if not count:
                return

    def __init__(self, pingChannel, echoChannel, units=Unit.kInches):
        """Create an instance of the Ultrasonic Sensor.
        This is designed to supchannel the Daventech SRF04 and Vex ultrasonic
        sensors.

        :param pingChannel: The digital output channel that sends the pulse
            to initiate the sensor sending the ping.
        :param echoChannel: The digital input channel that receives the echo.
            The length of time that the echo is high represents the round
            trip time of the ping, and the distance.
        :param units: The units returned in either kInches or kMillimeters
        """
        super().__init__()
        # Convert to DigitalInput and DigitalOutput if necessary
        self.pingAllocated = False
        self.echoAllocated = False
        
        if not hasattr(pingChannel, 'channel'):
            from .digitaloutput import DigitalOutput
            pingChannel = DigitalOutput(pingChannel)
            self.pingAllocated = True
            
        if not hasattr(echoChannel, 'channel'):
            from .digitalinput import DigitalInput
            echoChannel = DigitalInput(echoChannel)
            self.echoAllocated = True
            
        self.pingChannel = pingChannel
        self.echoChannel = echoChannel
        self.units = units
        self.pidSource = self.PIDSourceType.kDisplacement
        self.enabled = True # make it available for round robin scheduling

        self.valueEntry = None
        
        # set up counter for this sensor
        self.counter = Counter(self.echoChannel)
        self.counter.setMaxPeriod(1.0)
        self.counter.setSemiPeriodMode(True)
        self.counter.reset()
        
        isAutomatic = Ultrasonic.isAutomaticMode()
        self.setAutomaticMode(False)
        
        Ultrasonic.sensors.add(self)
        if isAutomatic:
            self.setAutomaticMode(True)
        
        Resource._add_global_resource(self)

        Ultrasonic.instances += 1
        hal.report(hal.UsageReporting.kResourceType_Ultrasonic,
                      Ultrasonic.instances)
        LiveWindow.addSensor("Ultrasonic", self.echoChannel.getChannel(), self)

    def free(self):
        isAutomatic = Ultrasonic.isAutomaticMode()
        self.setAutomaticMode(False)
            
        try:
            Ultrasonic.sensors.remove(self)
        except (KeyError, ValueError):
            pass
        
        if isAutomatic and len(Ultrasonic.sensors):
            self.setAutomaticMode(True)
        
        if self.pingAllocated and self.pingChannel:
            self.pingChannel.free()
            self.pingChannel = None
            
        if self.echoAllocated and self.echoChannel:
            self.echoChannel.free()
            self.echoChannel = None
        
        if self.counter != None:
            self.counter.free()
            self.counter = None
        
        super().free()

    def setAutomaticMode(self, enabling):
        """Turn Automatic mode on/off. When in Automatic mode, all sensors
        will fire in round robin, waiting a set time between each sensor.

        :param enabling:
            Set to true if round robin scheduling should start for all the
            ultrasonic sensors. This scheduling method assures that the
            sensors are non-interfering because no two sensors fire at the
            same time. If another scheduling algorithm is preferred, it
            can be implemented by pinging the sensors manually and waiting
            for the results to come back.
        :type enabling: bool
        """
        enabling = bool(enabling)
        if enabling == Ultrasonic.isAutomaticMode():
            return # ignore the case of no change
        
        with Ultrasonic._static_mutex:
            Ultrasonic.automaticEnabled = enabling

        if enabling:
            # Clear all the counters so no data is valid. No synchronization is
            # needed because the background task is stopped.
            for u in Ultrasonic.sensors:
                if u is not None:
                    u.counter.reset()
            
            # Start round robin task
            Ultrasonic._thread = threading.Thread(
                    target=Ultrasonic.ultrasonicChecker,
                    name="ultrasonicChecker")
            Ultrasonic.daemon = True
            Ultrasonic._thread.start()
        else:
            # Wait for background task to stop running
            Ultrasonic._thread.join()
            Ultrasonic._thread = None
            
            # Clear all the counters (data now invalid) since automatic mode is
            # disabled. No synchronization is needed because the background task is
            # stopped.
            for u in Ultrasonic.sensors:
                if u is not None:
                    u.counter.reset()

    def ping(self):
        """Single ping to ultrasonic sensor. Send out a single ping to the
        ultrasonic sensor. This only works if automatic (round robin) mode is
        disabled. A single ping is sent out, and the counter should count the
        semi-period when it comes in. The counter is reset to make the current
        value invalid.
        """
        # turn off automatic round robin if pinging single sensor
        self.setAutomaticMode(False)
        # reset the counter to zero (invalid data now)
        self.counter.reset()
        # do the ping to start getting a single range
        self.pingChannel.pulse(Ultrasonic.kPingTime)

    def isRangeValid(self):
        """Check if there is a valid range measurement. The ranges are
        accumulated in a counter that will increment on each edge of the
        echo (return) signal. If the count is not at least 2, then the range
        has not yet been measured, and is invalid.

        :returns: True if the range is valid
        :rtype: bool
        """
        return self.counter.get() > 1

    def getRangeInches(self):
        """Get the range in inches from the ultrasonic sensor.

        :returns: Range in inches of the target returned from the ultrasonic
            sensor. If there is no valid value yet, i.e. at least one
            measurement hasn't completed, then return 0.
        :rtype: float
        """
        if self.isRangeValid():
            return self.counter.getPeriod() * \
                    Ultrasonic.kSpeedOfSoundInchesPerSec / 2.0
        else:
            return 0

    def getRangeMM(self):
        """Get the range in millimeters from the ultrasonic sensor.

        :returns: Range in millimeters of the target returned by the
            ultrasonic sensor. If there is no valid value yet, i.e. at least
            one measurement hasn't complted, then return 0.
        :rtype: float
        """
        return self.getRangeInches() * 25.4
    
    def setPIDSourceType(self, pidSource):
        """Set which parameter you are using as a process
        control variable. 

        :param pidSource: An enum to select the parameter.
        :type  pidSource: :class:`.PIDSource.PIDSourceType`
        """
        if pidSource != self.PIDSourceType.kDisplacement:
            raise ValueError("Only displacement PID is allowed for ultrasonics.")
        self.pidSource = pidSource
        
    def getPIDSourceType(self):
        return self.pidSource

    def pidGet(self):
        """Get the range in the current DistanceUnit (PIDSource interface).

        :returns: The range in DistanceUnit
        :rtype: float
        """
        if self.units == self.Unit.kInches:
            return self.getRangeInches()
        elif self.units == self.Unit.kMillimeters:
            return self.getRangeMM()
        else:
            return 0.0

    def setDistanceUnits(self, units):
        """Set the current DistanceUnit that should be used for the
        PIDSource interface.

        :param units: The DistanceUnit that should be used.
        """
        
        if units not in [self.Unit.kInches, self.Unit.kMillimeters]:
            raise ValueError("Invalid units argument '%s'" % units)
        
        self.units = units

    def getDistanceUnits(self):
        """Get the current DistanceUnit that is used for the PIDSource
        interface.

        :returns: The type of DistanceUnit that is being used.
        """
        return self.units

    def isEnabled(self):
        """Is the ultrasonic enabled.

        :returns: True if the ultrasonic is enabled
        """
        return self.enabled

    def setEnabled(self, enable):
        """Set if the ultrasonic is enabled.

        :param enable: set to True to enable the ultrasonic
        :type  enable: bool
        """
        self.enabled = bool(enable)

    def initSendable(self, builder):
        builder.setSmartDashboardType("Ultrasonic")
        builder.addDoubleProperty("Value", self.getRangeInches, None)
