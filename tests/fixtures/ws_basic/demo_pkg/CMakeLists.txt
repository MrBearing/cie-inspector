cmake_minimum_required(VERSION 3.8)
project(demo_pkg)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)

add_executable(talker src/talker.cpp)
ament_target_dependencies(talker rclcpp sensor_msgs std_msgs example_interfaces)

install(TARGETS talker DESTINATION lib/${PROJECT_NAME})

ament_package()
