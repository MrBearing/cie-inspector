#include <chrono>
#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_msgs/msg/string.hpp"
#include "example_interfaces/srv/add_two_ints.hpp"

using namespace std::chrono_literals;

class Talker : public rclcpp::Node
{
public:
  Talker()
  : Node("talker")
  {
    sensor_group_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    worker_group_ = this->create_callback_group(rclcpp::CallbackGroupType::Reentrant);

    rclcpp::SubscriptionOptions scan_options;
    scan_options.callback_group = sensor_group_;
    scan_sub_ = this->create_subscription<sensor_msgs::msg::LaserScan>(
      "/scan", rclcpp::SensorDataQoS(),
      std::bind(&Talker::on_scan, this, std::placeholders::_1),
      scan_options);

    cmd_sub_ = this->create_subscription<std_msgs::msg::String>(
      "cmd", 10,
      [this](std_msgs::msg::String::SharedPtr msg) {(void)msg;});

    timer_ = this->create_wall_timer(
      500ms, std::bind(&Talker::on_timer, this), worker_group_);

    srv_ = this->create_service<example_interfaces::srv::AddTwoInts>(
      "add_two_ints",
      std::bind(&Talker::on_add, this, std::placeholders::_1, std::placeholders::_2));

    client_ = this->create_client<example_interfaces::srv::AddTwoInts>("add_two_ints");

    pub_ = this->create_publisher<std_msgs::msg::String>("chatter", 10);
  }

private:
  void on_scan(sensor_msgs::msg::LaserScan::SharedPtr msg) {(void)msg;}
  void on_timer() {}
  void on_add(
    example_interfaces::srv::AddTwoInts::Request::SharedPtr req,
    example_interfaces::srv::AddTwoInts::Response::SharedPtr res)
  {
    res->sum = req->a + req->b;
  }

  rclcpp::CallbackGroup::SharedPtr sensor_group_;
  rclcpp::CallbackGroup::SharedPtr worker_group_;
  rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr scan_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr cmd_sub_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::Service<example_interfaces::srv::AddTwoInts>::SharedPtr srv_;
  rclcpp::Client<example_interfaces::srv::AddTwoInts>::SharedPtr client_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<Talker>());
  rclcpp::shutdown();
  return 0;
}
