cmake_minimum_required(VERSION 3.8)
project(broken_pkg)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)

add_executable(broken src/broken.cpp)
ament_target_dependencies(broken rclcpp std_msgs)

ament_package()
