import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import OccupancyGrid
import numpy as np
import math
import cmath
import time

# constants
rotatechange = 0.1 
speedchange = 0.05
occ_bins = [-1, 0, 100, 101]
stop_distance = 0.10
front_angle = 30
front_angles = range(-front_angle,front_angle+1,1)
scanfile = 'lidar.txt'
mapfile = 'map.txt'

def euler_from_quaternion(x, y, z, w): # code from https://automaticaddison.com/how-to-convert-a-quaternion-into-euler-angles-in-python/
    """
    Convert a quaternion into euler angles (roll, pitch, yaw)
    roll is rotation around x in radians (counterclockwise)
    pitch is rotation around y in radians (counterclockwise)
    yaw is rotation around z in radians (counterclockwise)
    """
    t0 = +2.0 * (w * x + y * z)
    t1 = +1.0 - 2.0 * (x * x + y * y)
    roll_x = math.atan2(t0, t1)

    t2 = +2.0 * (w * y - z * x)
    t2 = +1.0 if t2 > +1.0 else t2
    t2 = -1.0 if t2 < -1.0 else t2
    pitch_y = math.asin(t2)

    t3 = +2.0 * (w * z + x * y)
    t4 = +1.0 - 2.0 * (y * y + z * z)
    yaw_z = math.atan2(t3, t4)

    return roll_x, pitch_y, yaw_z # in radians

class TableNav(Node):

    def __init__(self): 
        super().__init__('table_nav')
        
        # create publisher for moving TurtleBot
        self.publisher_ = self.create_publisher(Twist,'cmd_vel',10)
        
        # create subscription to track orientation
        self.odom_subscription = self.create_subscription(Odometry,'odom',self.odom_callback,10)
        self.odom_subscription  # prevent unused variable warning
        # initialize variables
        self.roll = 0
        self.pitch = 0
        self.yaw = 0

        # create subscription to track occupancy
        self.occ_subscription = self.create_subscription(OccupancyGrid,'map',self.occ_callback,qos_profile_sensor_data)
        self.occ_subscription  # prevent unused variable warning
        self.occdata = np.array([])
        
        # create subscription to track lidar
        self.scan_subscription = self.create_subscription(LaserScan,'scan',self.scan_callback,qos_profile_sensor_data)
        self.scan_subscription  # prevent unused variable warning
        self.laser_range = np.array([])


    def odom_callback(self, msg):
        orientation_quat =  msg.pose.pose.orientation
        self.roll, self.pitch, self.yaw = euler_from_quaternion(orientation_quat.x, orientation_quat.y, orientation_quat.z, orientation_quat.w)

    def occ_callback(self, msg):
        # self.get_logger().info('In occ_callback')
        # create numpy array
        msgdata = np.array(msg.data)
        # compute histogram to identify percent of bins with -1
        # occ_counts = np.histogram(msgdata,occ_bins)
        # calculate total number of bins
        # total_bins = msg.info.width * msg.info.height
        # log the info
        # self.get_logger().info('Unmapped: %i Unoccupied: %i Occupied: %i Total: %i' % (occ_counts[0][0], occ_counts[0][1], occ_counts[0][2], total_bins))

        # make msgdata go from 0 instead of -1, reshape into 2D
        oc2 = msgdata + 1
        # reshape to 2D array using column order
        # self.occdata = np.uint8(oc2.reshape(msg.info.height,msg.info.width,order='F'))
        self.occdata = np.uint8(oc2.reshape(msg.info.height,msg.info.width))
        # print to file
        np.savetxt(mapfile, self.occdata)


    def scan_callback(self, msg):
        # create numpy array
        self.laser_range = np.array(msg.ranges)
        # print to file
        np.savetxt(scanfile, self.laser_range)
        # replace 0's with nan
        self.laser_range[self.laser_range==0] = np.nan


    # function to rotate the TurtleBot
    def rotatebot(self, rot_angle):
        # create Twist object
        twist = Twist()
        
        # get current yaw angle
        current_yaw = self.yaw
        # log the info
        self.get_logger().info('Current: %f' % math.degrees(current_yaw))
        # using complex numbers to avoid problems when the angles go from 360 to 0, or from -180 to 180
        c_yaw = complex(math.cos(current_yaw),math.sin(current_yaw))
        # calculate desired yaw
        target_yaw = current_yaw + math.radians(rot_angle)
        # convert to complex notation
        c_target_yaw = complex(math.cos(target_yaw),math.sin(target_yaw))
        self.get_logger().info('Desired: %f' % math.degrees(cmath.phase(c_target_yaw)))
        # divide the two complex numbers to get the change in direction
        c_change = c_target_yaw / c_yaw
        # get the sign of the imaginary component to figure out which way we have to turn
        c_change_dir = np.sign(c_change.imag)

        # publish rotation command
        twist.linear.x, twist.angular.z = 0.0, c_change_dir * rotatechange
        self.publisher_.publish(twist)


        # we will use the c_dir_diff variable to see if we can stop rotating
        # if the rotation direction was 1.0, then we will want to stop when the c_dir_diff
        # becomes -1.0, and vice versa

        c_dir_diff = c_change_dir
        while(c_change_dir * c_dir_diff > 0):
            # allow the callback functions to run
            rclpy.spin_once(self)
            current_yaw = self.yaw
            # convert the current yaw to complex form
            c_yaw = complex(math.cos(current_yaw),math.sin(current_yaw))
            # self.get_logger().info('Current Yaw: %f' % math.degrees(current_yaw))
            # get difference in angle between current and target
            c_change = c_target_yaw / c_yaw
            # get the sign to see if we can stop
            c_dir_diff = np.sign(c_change.imag)
            # self.get_logger().info('c_change_dir: %f c_dir_diff: %f' % (c_change_dir, c_dir_diff))

        self.get_logger().info('End Yaw: %f' % math.degrees(current_yaw))
        # stop the rotation
        twist.angular.z = 0.0
        self.publisher_.publish(twist)


    # all-in-one function for linear movement

    # first input == direction of movement (forward or backward)
    # second input == angle to check (0, 90, 180, 270)
    # third == check if more or less than the input distance (more or less)
    # fourth == distance to check

    def move_til(self, direction, angle, more_less, dist):

        self.get_logger().info('Moving %s until distance at %s degrees is %s than %f' % (direction, angle, more_less, dist))

        move_dict = {'forward': 0.1, 
                    'backward': -0.1,
                    'more': True,
                    'less': False}

        # create Twist object, publish movement
        twist = Twist()
        twist.linear.x,twist.angular.z = move_dict[direction],0.0
        time.sleep(1)
        self.publisher_.publish(twist)

        self.get_logger().info('Linear movement initiated')

        # create parameter to check distance
        check_dist = self.laser_range[angle]
        while math.isnan(check_dist) or (((not math.isnan(check_dist)) and (check_dist < dist)) == move_dict[more_less]):

            #allow the callback functions to run
            rclpy.spin_once(self)
            check_dist = self.laser_range[angle]

            # log the info
            self.get_logger().info('Distance at %s degrees: %f' % (angle, check_dist))

        # stop moving
        twist.linear.x = 0.0
        time.sleep(1)
        self.publisher_.publish(twist)


    #function to simplify right angle rotation
    def right_angle_rotate(self, orientation):

        self.get_logger().info('Turning 90 degrees %s' % orientation)

        turn_dict = {'clockwise': 270,
                    'anticlockwise': 90}
        
        self.rotatebot(turn_dict[orientation])

    def stopbot(self):
        self.get_logger().info('In stopbot')
        # create Twist object, publish movement
        twist = Twist()
        twist.linear.x = 0.0
        twist.angular.z = 0.0
        time.sleep(1)
        self.publisher_.publish(twist)

    #function to locate table 6
    #table 6 is located at the top left quadrant of the robot
    #robot navigates to it by finding the shortest distance in the quadrant
    #and rotating to that angle
    #then wait for the limit switch to be depressed
    #then reverses to its starting position
    def locate_table6(self, starting_angle, ending_angle):
        angle = np.nanargmin(self.laser_range[starting_angle:ending_angle])
        self.get_logger().info('Table located: %d %f m' % (angle, self.laser_range[angle]))
        self.rotatebot(angle)
        self.move_til('forward', 0, 'less', 0.3)
        while not self.limit_switch:
            self.stopbot()

        while rclpy.ok():
            rclpy.spin_once(self)
            if self.limit_switch:
                break
        
        self.move_til('backward', 0, 'less', 0.5)
        self.rotatebot(-angle)
        self.move_til('backward', 0, 'less', 0.5)


    def table1(self):
        self.get_logger().info('Navigating to Table 1')
        try:
            while rclpy.ok():
                if self.laser_range.size != 0:
                    #move until distance at 0 degrees is more than 0.7
                    self.move_til('backward', 180, 'less', 0.5)

                    #calibrate
                    #self.calibrate(left_wall=True)

                    #rotate 90 degrees anticlockwise
                    self.right_angle_rotate('clockwise')

                    #move forward until distance at 0 degrees is less than 0.5
                    self.move_til('forward', 0, 'less', 0.5)

                    #rotate 90 degrees anticlockwise
                    self.right_angle_rotate('anticlockwise')

                    #move forward until distance at 0 degrees is less than 0.1
                    self.move_til('forward', 0, 'less', 0.5)

                    self.right_angle_rotate('anticlockwise')

                    self.move_til('forward', 0, 'less', 0.3)
                    
                    break

                # allow the callback functions to run
                rclpy.spin_once(self)


        except Exception as e:
            print(e)
        
        # Ctrl-c detected
        finally:
            # stop moving
            self.stopbot()

    def table6(self):
            
        self.get_logger().info('Navigating to Table 6')

        try:

            while rclpy.ok():
                if self.laser_range.size != 0:
                    #move backward until distance at 180 degrees is less than 0.5
                    self.move_til('backward', 180, 'less', 0.5)

                    #rotate 90 degrees anticlockwise
                    self.right_angle_rotate('anticlockwise')

                    #move forward until distance at 0 degrees is less than 0.5
                    self.move_til('forward', 0, 'less', 0.5)

                    #rotate 90 degrees anticlockwise
                    self.right_angle_rotate('clockwise')

                    #move forward until distance at 0 degrees is less than 1.34
                    self.move_til('forward', 0, 'less', 1.34)

                    #rotate 90 degrees anticlockwise
                    self.right_angle_rotate('anticlockwise')

                    #move forward until distance at 0 degrees is less than 1.4
                    self.move_til('forward', 0, 'less', 1.4)

                    break

                # allow the callback functions to run
                rclpy.spin_once(self)

            self.locate_table6(0, 90)

        except Exception as e:
            print(e)
        
        # Ctrl-c detected
        finally:
            # stop moving
            self.stopbot()


def main(args=None):
    rclpy.init(args=args)
    table_nav = TableNav()
    
    # rclpy.spin(table_nav)

    #receive input from user to know which table to go to, then execute corresponding table function
    #table_dict = {1: table_nav.table1, 2: table_nav.table2, 3: table_nav.table3, 4: table_nav.table4, 5: table_nav.table5}
    #selection = int(input(" Please enter the table number you would like to go to (1/2/3/4/5): "))
    #execute table function based on user input
    #table_dict[selection]()

    #execute function to navigate to table 1
    table_nav.table1()

    # destroy the node explicitly
    table_nav.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()