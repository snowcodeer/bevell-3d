# SO-101 gripper (third party)

From The Robot Studio's [SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) repository,
commit in `COMMIT`, under the Apache License 2.0 (`LICENSE`), unmodified:

- `so101_new_calib.xml`: the arm's MuJoCo model. `bevell3d/scissors_sim.py` takes the gripper's
  jaw poses and hinge from it.
- `assets/wrist_roll_follower_so101_v1.stl` (the fixed jaw) and `assets/moving_jaw_so101_v1.stl`.

Used to fit the tool fingers to the real jaws and to simulate the gripper working scissors.
