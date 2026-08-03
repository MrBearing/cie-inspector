cmake_minimum_required(VERSION 3.8)
project(tricky_pkg)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)

set(TRICKY_SOURCES src/tricky.cpp)
add_executable(tricky ${TRICKY_SOURCES})
ament_target_dependencies(tricky rclcpp std_msgs)

# UNKNOWN_SRCS is never set — the tool must record this, not guess.
add_executable(mystery ${UNKNOWN_SRCS})

ament_package()
