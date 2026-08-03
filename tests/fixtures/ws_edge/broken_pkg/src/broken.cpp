#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"

class Broken : public rclcpp::Node
{
public:
  Broken()
  : Node("broken")
  {
    sub_ = this->create_subscription<std_msgs::msg::String>(
      "ok_topic", 10,
      [](std_msgs::msg::String::SharedPtr) {});
  }

  // Everything below this line is not valid C++ — the tool must still
  // produce partial results without crashing.
  void oops( {{{ this is definitely not C++ ))))
  template <<>> broken syntax %%%
};

random garbage outside any declaration @@@
