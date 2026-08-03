cmake_minimum_required(VERSION 3.8)
project(component_pkg)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)

add_library(listener_component SHARED src/listener_component.cpp)
ament_target_dependencies(listener_component rclcpp rclcpp_components std_msgs)
rclcpp_components_register_node(listener_component
  PLUGIN "component_pkg::Listener"
  EXECUTABLE listener)

ament_package()
