#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"
#include "rclcpp_components/register_node_macro.hpp"

namespace component_pkg
{

class Listener : public rclcpp::Node
{
public:
  explicit Listener(const rclcpp::NodeOptions & options)
  : Node("listener", options)
  {
    sub_ = this->create_subscription<std_msgs::msg::String>(
      "chatter", 10,
      [this](std_msgs::msg::String::SharedPtr msg) {
        RCLCPP_INFO(this->get_logger(), "I heard: '%s'", msg->data.c_str());
      });
  }

private:
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_;
};

}  // namespace component_pkg

RCLCPP_COMPONENTS_REGISTER_NODE(component_pkg::Listener)
