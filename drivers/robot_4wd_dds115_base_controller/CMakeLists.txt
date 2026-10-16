cmake_minimum_required(VERSION 3.0.2)
project(robot_4wd_dds115_base_controller)

set(CMAKE_CXX_STANDARD 14)
add_compile_options(-Wall -Wextra -O2)

find_package(catkin REQUIRED COMPONENTS
  roscpp
  rospy
  std_msgs
  nav_msgs
  geometry_msgs
  tf
  serial
)

catkin_package(
  INCLUDE_DIRS include
  LIBRARIES ddsm115_protocol
  CATKIN_DEPENDS roscpp std_msgs nav_msgs geometry_msgs tf serial
)

include_directories(
  include
  ${catkin_INCLUDE_DIRS}
)

# ── C++ protocol library ──────────────────────────────────────────────────────
add_library(ddsm115_protocol src/ddsm115_protocol.cpp)
target_link_libraries(ddsm115_protocol ${catkin_LIBRARIES})

# ── C++ ROS node ──────────────────────────────────────────────────────────────
add_executable(base_controller_node src/base_controller_node.cpp)
target_link_libraries(base_controller_node
  ddsm115_protocol
  ${catkin_LIBRARIES}
)

install(TARGETS base_controller_node ddsm115_protocol
  RUNTIME DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
  LIBRARY DESTINATION ${CATKIN_PACKAGE_LIB_DESTINATION}
)

install(DIRECTORY include/${PROJECT_NAME}/
  DESTINATION ${CATKIN_PACKAGE_INCLUDE_DESTINATION}
)

# ── Python (kept as legacy/reference) ────────────────────────────────────────
catkin_install_python(PROGRAMS scripts/base_controller_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY ddsm115/
  DESTINATION ${CATKIN_PACKAGE_PYTHON_DESTINATION}
  FILES_MATCHING PATTERN "*.py"
)

install(DIRECTORY config launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)
