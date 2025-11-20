README:

This skill is special because it also requires a .DLL file to be placed in the game folder of American Truck Simulator or Euro Truck Simulator to work so that the game will send the required data to the skill.

The DLL is already included in this skill folder, scs-telemetry.dll.  It was sourced from https://github.com/RenCloud/scs-sdk-plugin (September 21, 2023 release, v.1.12.1)

You can either manually download / move this file into your game directory in the bin/win_x64/plugins folder or you can point the skill to your install directories for ATS/ETS and save the skill and the skill will try to copy over that .dll file itself to the proper location.

Here are the variables available through telemetry:

### Common Unsigned Integers
- `time_abs`

### Config Unsigned Integers
- `gears`
- `gears_reverse`
- `retarderStepCount`
- `truckWheelCount`
- `selectorCount`
- `time_abs_delivery`
- `maxTrailerCount`
- `unitCount`
- `plannedDistanceKm`

### Truck Channel Unsigned Integers
- `shifterSlot`
- `retarderBrake`
- `lightsAuxFront`
- `lightsAuxRoof`
- `truck_wheelSubstance[16]`
- `hshifterPosition[32]`
- `hshifterBitmask[32]`

### Gameplay Unsigned Integers
- `jobDeliveredDeliveryTime`
- `jobStartingTime`
- `jobFinishedTime`

### Common Integers
- `restStop`

### Truck Integers
- `gear`
- `gearDashboard`
- `hshifterResulting[32]`

### Gameplay Integers
- `jobDeliveredEarnedXp`

### Common Floats
- `scale`

### Config Floats
- `fuelCapacity`
- `fuelWarningFactor`
- `adblueCapacity`
- `adblueWarningFactor`
- `airPressureWarning`
- `airPressurEmergency`
- `oilPressureWarning`
- `waterTemperatureWarning`
- `batteryVoltageWarning`
- `engineRpmMax`
- `gearDifferential`
- `cargoMass`
- `truckWheelRadius[16]`
- `gearRatiosForward[24]`
- `gearRatiosReverse[8]`
- `unitMass`

### Truck Floats
- `speed`
- `engineRpm`
- `userSteer`
- `userThrottle`
- `userBrake`
- `userClutch`
- `gameSteer`
- `gameThrottle`
- `gameBrake`
- `gameClutch`
- `cruiseControlSpeed`
- `airPressure`
- `brakeTemperature`
- `fuel`
- `fuelAvgConsumption`
- `fuelRange`
- `adblue`
- `oilPressure`
- `oilTemperature`
- `waterTemperature`
- `batteryVoltage`
- `lightsDashboard`
- `wearEngine`
- `wearTransmission`
- `wearCabin`
- `wearChassis`
- `wearWheels`
- `truckOdometer`
- `routeDistance`
- `routeTime`
- `speedLimit`
- `truck_wheelSuspDeflection[16]`
- `truck_wheelVelocity[16]`
- `truck_wheelSteering[16]`
- `truck_wheelRotation[16]`
- `truck_wheelLift[16]`
- `truck_wheelLiftOffset[16]`

### Gameplay Floats
- `jobDeliveredCargoDamage`
- `jobDeliveredDistanceKm`
- `refuelAmount`

### Job Floats
- `cargoDamage`

### Config Bools
- `truckWheelSteerable[16]`
- `truckWheelSimulated[16]`
- `truckWheelPowered[16]`
- `truckWheelLiftable[16]`
- `isCargoLoaded`
- `specialJob`

### Truck Bools
- `parkBrake`
- `motorBrake`
- `airPressureWarning`
- `airPressureEmergency`
- `fuelWarning`
- `adblueWarning`
- `oilPressureWarning`
- `waterTemperatureWarning`
- `batteryVoltageWarning`
- `electricEnabled`
- `engineEnabled`
- `wipers`
- `blinkerLeftActive`
- `blinkerRightActive`
- `blinkerLeftOn`
- `blinkerRightOn`
- `lightsParking`
- `lightsBeamLow`
- `lightsBeamHigh`
- `lightsBeacon`
- `lightsBrake`
- `lightsReverse`
- `lightsHazard`
- `cruiseControl`
- `truck_wheelOnGround[16]`
- `shifterToggle[2]`
- `differentialLock`
- `liftAxle`
- `liftAxleIndicator`
- `trailerLiftAxle`
- `trailerLiftAxleIndicator`

### Gameplay Bools
- `jobDeliveredAutoparkUsed`
- `jobDeliveredAutoloadUsed`

### Config FVectors
- `cabinPositionX`
- `cabinPositionY`
- `cabinPositionZ`
- `headPositionX`
- `headPositionY`
- `headPositionZ`
- `truckHookPositionX`
- `truckHookPositionY`
- `truckHookPositionZ`
- `truckWheelPositionX[16]`
- `truckWheelPositionY[16]`
- `truckWheelPositionZ[16]`

### Truck FVectors
- `lv_accelerationX`
- `lv_accelerationY`
- `lv_accelerationZ`
- `av_accelerationX`
- `av_accelerationY`
- `av_accelerationZ`
- `accelerationX`
- `accelerationY`
- `accelerationZ`
- `aa_accelerationX`
- `aa_accelerationY`
- `aa_accelerationZ`
- `cabinAVX`
- `cabinAVY`
- `cabinAVZ`
- `cabinAAX`
- `cabinAAY`
- `cabinAAZ`

### Truck FPlacements
- `cabinOffsetX`
- `cabinOffsetY`
- `cabinOffsetZ`
- `cabinOffsetrotationX`
- `cabinOffsetrotationY`
- `cabinOffsetrotationZ`
- `headOffsetX`
- `headOffsetY`
- `headOffsetZ`
- `headOffsetrotationX`
- `headOffsetrotationY`
- `headOffsetrotationZ`

### Truck DPlacements
- `coordinateX`
- `coordinateY`
- `coordinateZ`
- `rotationX`
- `rotationY`
- `rotationZ`

### Config Strings
- `truckBrandId`
- `truckBrand`
- `truckId`
- `truckName`
- `cargoId`
- `cargo`
- `cityDstId`
- `cityDst`
- `compDstId`
- `compDst`
- `citySrcId`
- `citySrc`
- `compSrcId`
- `compSrc`
- `shifterType`
- `truckLicensePlate`
- `truckLicensePlateCountryId`
- `truckLicensePlateCountry`
- `jobMarket`

### Gameplay Strings
- `fineOffence`
- `ferrySourceName`
- `ferryTargetName`
- `ferrySourceId`
- `ferryTargetId`
- `trainSourceName`
- `trainTargetName`
- `trainSourceId`
- `trainTargetId`

### Config ULL
- `jobIncome`

### Gameplay LL
- `jobCancelledPenalty`
- `jobDeliveredRevenue`
- `fineAmount`
- `tollgatePayAmount`
- `ferryPayAmount`
- `trainPayAmount`

### Special Bools
- `onJob`
- `jobFinished`
- `jobCancelled`
- `jobDelivered`
- `fined`
- `tollgate`
- `ferry`
- `train`
- `refuel`
- `refuelPayed`


### Trailer Data
- `trailer[10]`