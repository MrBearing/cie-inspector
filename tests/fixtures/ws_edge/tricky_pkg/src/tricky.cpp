#include <chrono>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"

using namespace std::chrono_literals;

rclcpp::CallbackGroup::SharedPtr make_group(rclcpp::Node * node);
std::string topic_from_config();

class Tricky : public rclcpp::Node
{
public:
  Tricky()
  : Node("tricky")
  {
    // Group obtained through a helper function — not traceable statically.
    group_ = make_group(this);

    // Topic name is a runtime expression.
    sub_ = this->create_subscription<std_msgs::msg::String>(
      topic_from_config(), 10,
      [](std_msgs::msg::String::SharedPtr) {});

    // Group variable exists but was never seen at a create_callback_group site.
    timer_ = this->create_wall_timer(100ms, [this]() {}, group_);

    // Period is a member variable, not a literal.
    slow_timer_ = this->create_wall_timer(period_, [this]() {});
  }

private:
  rclcpp::CallbackGroup::SharedPtr group_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::TimerBase::SharedPtr slow_timer_;
  std::chrono::milliseconds period_{250};
};
