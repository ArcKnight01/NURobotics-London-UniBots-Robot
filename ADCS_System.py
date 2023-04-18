import sys
import os
import board
import busio
import adafruit_bno055
import time
from ADCS_Util import *
import csv

class ADCS(object):
    def __init__(self, test_points:int=10, verbose:bool=False):
        self.__test_points = test_points
        self.__verbose = verbose
        self.__i2c = busio.I2C(board.SCL, board.SDA)
        self.__sensor = adafruit_bno055.BNO055_I2C(self.__i2c)
        self.__acceleration = (0,0,0)
        self.__previous_acceleration = (0,0,0)
        self.__velocity = (0,0,0)
        self.__previous_velocity = (0,0,0)
        self.__position = (0,0,0)
        
        self.__accelerometer_offset = self.calibrate_accelerometer()
        self.__offset_mag = self.calibrate_mag()
        self.__gyro_offset = self.calibrate_gyro()
        
        self.__initial_orientation = self.set_initial(self.__offset_mag)

        self.__orientation = self.__initial_orientation
        self.__previous_orientation = self.__initial_orientation

        self.__orientation_zeroed = self.zero_orientation()
        #zero the orientation to intitial orientation of robot
        
        
        self.__startTime = time.time()
        self.__currentTime = time.time() - self.__startTime
        self.init_csv()

    def update(self):
        self.__currentTime = time.time() - self.__startTime
        self.__euler = self.__sensor.euler
        self.__quaternion = self.__sensor.quaternion
        self.__linear_acceleration = self.__sensor.linear_acceleration
        self.__gravity = self.__sensor.gravity
        self.__raw_acceleration = self.__sensor.acceleration
        
        self.__magnetometer = self.__sensor.magnetic
        self.__magnetometer = (self.__magnetometer[0] - self.__offset_mag[0], self.__magnetometer[1] - self.__offset_mag[1], self.__magnetometer[2] - self.__offset_mag[2])

        gyroX, gyroY, gyroZ = self.__gyro = self.__sensor.gyro

        #get gyro offset
        offset_gyro = self.__gyro_offset

        #subtract gyro readings by the offset
        gyroX = gyroX *180/np.pi - offset_gyro[0]
        gyroY = gyroY *180/np.pi - offset_gyro[1]
        gyroZ = gyroZ *180/np.pi - offset_gyro[2]

        #set gyro to corrected values
        self.__gyro = (gyroX, gyroY, gyroZ)

        #get acceleration offset
        offset_accel = self.__accelerometer_offset
        self.__previous_acceleration = self.__acceleration
        self.__previous_velocity = self.__velocity
        accelX, accelY, accelZ = self.__acceleration = self.__linear_acceleration
        
        accelX = accelX - offset_accel[0]
        accelY = accelY - offset_accel[1]
        accelZ = accelZ - offset_accel[2]

        #When the robot is still, the accel values are near 0. In this case, set accel values to zero.
        accelX = round(accelX,2)
        accelY = round(accelY,2)
        accelZ = round(accelZ,2)

        if (abs(accelX) < 0.75):
            accelX = 0
        if (abs(accelY < 0.75)):
            accelY = 0
        if (abs(accelZ < 0.75)):
            accelZ = 0
       
        #update accel values
        self.__acceleration = (accelX, accelY, accelZ)

        self.__delta_acceleration = (self.__acceleration[0] - self.__previous_acceleration[0],self.__acceleration[1] - self.__previous_acceleration[1],self.__acceleration[2] - self.__previous_acceleration[2])
        #get roll,pitch,yaw with acceleration-magnetic data
        self.__roll_am = roll_am(self.__acceleration[0], self.__acceleration[1], self.__acceleration[2])
        self.__pitch_am = pitch_am(self.__acceleration[0], self.__acceleration[1], self.__acceleration[2])
        self.__yaw_am = yaw_am(self.__acceleration[0], self.__acceleration[1], self.__acceleration[2], self.__magnetometer[0], self.__magnetometer[1], self.__magnetometer[2])
    
        #correct for zeroed values (when zeroed, subtract the value by the zeroed value)
        self.__roll_am = self.__roll_am - self.__orientation_zeroed[0]
        self.__pitch_am = self.__pitch_am - self.__orientation_zeroed[1]
        self.__yaw_am = self.__yaw_am - self.__orientation_zeroed[2]

        #reset the timer
        self.__endTime = time.time()
        #calculate delta time
        delT = self.__endTime - self.__startTime
        #restart the timer
        self.__startTime = time.time()

        #get roll,pitch,yaw with respect to gyro data
        self.__roll_gy = roll_gy(self.__previous_orientation[0], delT, self.__gyro[0])
        self.__pitch_gy = pitch_gy(self.__previous_orientation[1], delT, self.__gyro[1])
        self.__yaw_gy = yaw_gy(self.__previous_orientation[2], delT, self.__gyro[2])

        #correct for zeroed values (when zeroed, subtract the value by the zeroed value)
        self.__roll_gy = self.__roll_gy - self.__orientation_zeroed[0]
        self.__pitch_gy = self.__pitch_gy - self.__orientation_zeroed[1]
        self.__yaw_gy = self.__yaw_gy - self.__orientation_zeroed[2]

        #get roll,pitch,yaw using fusion of am and gyro
        self.__roll = roll_F(self.__previous_orientation[0], delT, self.__gyro[0], self.__acceleration[0],self.__acceleration[1], self.__acceleration[2], 0.5) 
        self.__pitch = pitch_F(self.__previous_orientation[1], delT, self.__gyro[1], self.__acceleration[0],self.__acceleration[1], self.__acceleration[2], 0.5)
        self.__yaw = yaw_F(self.__previous_orientation[0], delT, self.__gyro[0], self.__acceleration[0],self.__acceleration[1], self.__acceleration[2], self.__magnetometer[0], self.__magnetometer[1], self.__magnetometer[2],0.5)

        #correct for zeroed values (when zeroed, subtract the value by the zeroed value)
        self.__roll = self.__roll - self.__orientation_zeroed[0]
        self.__pitch = self.__pitch - self.__orientation_zeroed[1]
        self.__yaw = self.__yaw - self.__orientation_zeroed[2]

        #set the orientation based on roll pitch and yaw values
        self.__orientation = (self.__roll, self.__pitch, self.__yaw)
        #set previous orientation to roll pitch and yaw based on gyro data?
        self.__previous_orientation = [self.__roll_gy, self.__pitch_gy, self.__yaw_gy]

        #update velocity
        dt = delT
        #dt = 1
        self.__velocity = (self.__velocity[0] + self.__delta_acceleration[0]*dt, self.__velocity[1] + self.__delta_acceleration[1]*dt, self.__velocity[2] + self.__delta_acceleration[2]*dt)
        self.__delta_velocity = (self.__velocity[0] - self.__previous_velocity[0],self.__velocity[1] - self.__previous_velocity[1],self.__velocity[2] - self.__previous_velocity[2])
        #update position
        self.__position = (self.__position[0] + self.__delta_velocity[0]*dt, self.__position[1] + self.__delta_velocity[1]*dt, self.__position[2]  +self.__delta_velocity[2]*dt)
        
        
        if(self.__verbose):
            print(f"[INFO] Raw Acceleration {self.__raw_acceleration}")
            print(f"[INFO] Linear Acceleration {self.__linear_acceleration}")
            print(f"[INFO] Acceleration {self.__acceleration}")

            print(f"[INFO] Velocity {self.__velocity}")
            print(f"[INFO] Position {self.__position}")
            # print(f"Magnetometer {self.__magnetometer}")
            # print(f"Gyroscope {self.__gyro}")
            # print(f"Euler orientation {self.__euler}")
            # print(f"Quaternion {self.__quaternion}")
            
            print(f"[INFO] Gravity {self.__gravity}")
            print(f"[INFO] RPY_GY {(round(self.__roll_gy,2), round(self.__pitch_gy,2), round(self.__yaw_gy,2))} (degrees)")
            print(f"[INFO] RPY_AM {(round(self.__roll_am,2), round(self.__pitch_am,2), round(self.__yaw_am,2))} (degrees)")
            print(f"[INFO] RPY_F {self.__orientation}")

    def calibrate_accelerometer(self):
        calibration_pause = 1

        accelXList = [];
        accelYList = [];
        accelZList = [];

        print("Preparing to calibrate accelerometer. Please hold still.")
        time.sleep(calibration_pause) # pause before calibrating (1s)
        print("Calibrating...")
        numTestPoints = 0;
        while numTestPoints < self.__test_points:
            accelX, accelY, accelZ = self.__sensor.linear_acceleration
            if(self.__verbose):
                print(f"Acceleration (x,y,z) @ n={numTestPoints}: {(accelX, accelY, accelZ)}")
            accelXList.append(accelX)
            accelYList.append(accelY)
            accelZList.append(accelZ)
            numTestPoints += 1
            time.sleep(1)
        print("[CALIBRATION] Calibration complete.")
        # print(rollList)
        time.sleep(calibration_pause) # break after calibrating

        avgX = np.mean((np.min(accelXList),np.max(accelXList)))
        avgY = np.mean((np.min(accelYList), np.max(accelYList)))
        avgZ = np.mean((np.min(accelZList), np.max(accelZList)))
        
        accel_offsets = [avgX,avgY,avgZ]

        print(f"[CALIBRATION] Acceleration offsets: {accel_offsets}.")
        return accel_offsets
    def zero_orientation(self):
        self.__orientation_zeroed = self.__orientation
        self.__roll, self.__pitch, self.__yaw = self.__orientation
        
        self.__roll = self.__roll - self.__orientation_zeroed[0]
        self.__pitch = self.__pitch - self.__orientation_zeroed[1]
        self.__yaw = self.__yaw - self.__orientation_zeroed[2]
        self.__orientation = (self.__roll, self.__pitch, self.__yaw)
        return(self.__orientation_zeroed)

    def set_initial(self, mag_offset = [0,0,0]):
        calibration_pause=.001
        accelX, accelY, accelZ =  self.__sensor.acceleration #m/s^2
        magX, magY, magZ = self.__sensor.magnetic #gauss

        #Sets the initial position for plotting and gyro calculations.
        print("[CALIBRATION] Preparing to set initial orientation. Please hold the IMU still.")
        time.sleep(calibration_pause)
        print("[CALIBRATION] Setting orientation...")
        
        #Calibrate magnetometer readings. Defaults to zero until you
        magX = magX - mag_offset[0]
        magY = magY - mag_offset[1]
        magZ = magZ - mag_offset[2]

        roll = roll_am(accelX, accelY,accelZ)
        pitch = pitch_am(accelX,accelY,accelZ)
        yaw = yaw_am(accelX,accelY,accelZ,magX,magY,magZ)

        print("[CALIBRATION] Initial orientation set.")
        print(f"[CALIBRATION] Initial Orientation (Roll,Pitch,Yaw): {[roll,pitch,yaw]}") # display the initial position
        return [roll,pitch,yaw]
    
    
    def calibrate_mag(self):
        calibration_pause = .001
        rollList = [];
        pitchList = [];
        yawList = [];
        print("Preparing to calibrate magnetometer. Please wave around.")
        time.sleep(calibration_pause) # pause before calibrating
        print("Calibrating...")
        numTestPoints = 0;
        while numTestPoints < self.__test_points:
            magX, magY, magZ = self.__sensor.magnetic
            if(self.__verbose):
                print(f"Mag(x,y,z)@{numTestPoints}: {(magX, magY, magZ)}")
            rollList.append(magX)
            pitchList.append(magY)
            yawList.append(magZ)
            numTestPoints += 1
            time.sleep(calibration_pause)
        print("Calibration complete.")
        # print(rollList)
        time.sleep(calibration_pause) # break after calibrating
        avgX = np.mean((np.min(rollList),np.max(rollList)))
        avgY = np.mean((np.min(pitchList), np.max(pitchList)))
        avgZ = np.mean((np.min(yawList), np.max(yawList)))
        calConstants = [avgX,avgY,avgZ]
        print(calConstants)
        return calConstants
        

    def calibrate_gyro(self):
        calibration_pause=.001
        rollList = [];
        pitchList = [];
        yawList = [];
        print("Preparing to calibrate gyroscope. Please hold still.")
        time.sleep(calibration_pause) # pause before calibrating
        print("Calibrating...")

        numTestPoints = 0;
        while numTestPoints < self.__test_points:
            gyroX, gyroY, gyroZ = self.__sensor.gyro
            if(self.__verbose):
                print(f"Gyro(x,y,z)@{numTestPoints}: {(gyroX, gyroY, gyroZ)}")
            rollList = rollList + [gyroX]
            pitchList = pitchList + [gyroY] 
            yawList = yawList + [gyroZ]
            numTestPoints += 1
            time.sleep(calibration_pause)
        print("Calibration complete.")
        
        time.sleep(calibration_pause) # break after calibrating
        avgX = np.mean((np.min(rollList),np.max(rollList)))
        avgY = np.mean((np.min(pitchList), np.max(pitchList)))
        avgZ = np.mean((np.min(yawList), np.max(yawList)))
        calConstants = [avgX,avgY,avgZ]
        print(calConstants)
        return calConstants
        #return [0, 0, 0]

    def find_north(self):
        # get gravity direction (down)
        accelX, accelY, accelZ = self.__gravity #m/s^2 #previously self.__acceleration, which works if still
        gravityVec = [accelX,accelY,accelZ]/np.sqrt(accelX**2+accelY**2+accelZ**2) # unit vector direction
        # get magnetic field direction
        magX, magY, magZ = self.__magnetometer #gauss
        magVec = [magX,magY,magZ]/np.sqrt(magX**2+magY**2+magZ**2) # unit vector direction
        # get East (cross gravity and mag field directions)
        east = np.cross(gravityVec,magVec)
        # get North (cross East and gravity)
        north = np.cross(east,gravityVec)
        rollN = np.arctan2(north[2],north[1])
        pitchN = np.arctan2(north[2],north[0])
        # assuming roll and pitch are zero - calculate the yaw from x and y values of North direction
        yawN = np.arctan2(north[0],north[1])
        return ([(180/np.pi)*rollN,(180/np.pi)*pitchN,(180/np.pi)*yawN])

    def get_data(self):
        return(self.__currentTime, self.__raw_acceleration, self.__acceleration, self.__velocity, self.__position, self.__orientation)

    def init_csv(self):
        with open('auv_data.csv', 'w') as csvfile:
            data = csv.writer(csvfile, delimiter =',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            data.writerow(['Time','AccelX', 'AccelY','AccelZ', 'VelX', 'VelY', 'VelZ', 'PosX', 'PosY', 'PosZ', 'Roll', 'Pitch', 'Yaw'])

    def add_to_csv(self):
        time, _, acceleration, velocity, position, orientation = self.get_data()
        accelX, accelY, accelZ = acceleration
        velX, velY, velZ = velocity
        posX, posY, posZ = position
        roll, pitch, yaw = orientation
        self.__data = [time, accelX, accelY, accelZ, velX, velY, velZ, posX, posY, posZ, roll, pitch, yaw]
        with open('auv_data.csv', 'a') as csvfile:
            data = csv.writer(csvfile, delimiter =',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            data.writerow(self.__data)
        self.__data = []
        pass

if __name__ == '__main__':
    # print("Args passed: ", end='')
    # print([sys.argv[0]], end='|')
    # print(sys.argv[1:], end = '||')
    
    # print(len([*sys.argv[1:]] ))
    if(sys.argv[1:] != list()):
        print(f"test_points={sys.argv[1:][0]}, verbose={sys.argv[1:][1]}")
        # print("args passed!")
        # print(sys.argv[1:])
        imu = ADCS(test_points=int(sys.argv[1]), verbose=(True if str(sys.argv[2])=='True' else False))
    else:
        # print("no args passed!")
        imu = ADCS(test_points=10, verbose=False)
    while(True):
        imu.update()
        imu.add_to_csv()
        t, raw, accel, vel, pos, rpy = imu.get_data()
        # print(f"Raw:{(round(raw[1:][0],2), round(raw[1:][1],2))}|Accel:{(round(accel[1:][0],2),}|Vel:{vel}|Pos:{pos}|Rpy:{rpy}")

        pass
