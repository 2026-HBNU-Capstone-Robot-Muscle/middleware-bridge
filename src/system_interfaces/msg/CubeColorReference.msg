# Center colors from the accepted six-face scan, in U,R,F,D,L,B order.
# Each consecutive triple is B,G,R, not a cube marker ID or inferred pose.
std_msgs/Header header
string scan_id
uint8[18] center_bgr
