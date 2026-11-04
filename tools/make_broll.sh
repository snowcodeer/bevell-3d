#!/bin/zsh
# B-roll for the demo video, from the servo example: two turntables as H.264 MP4s in out/broll/.
#   1. servo_scan_and_tree.mp4: the scan's smooth NURBS CAD (grey) beside Muse Spark's
#      editable tree of it (blue).
#   2. servo_fixture.mp4: the robot fixture with the servo seated and the tag in its recess.
set -e
cd "$(dirname "$0")/.."
B=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
S=${1:-out/scans/example-servo/result}
O=out/broll
mkdir -p $O
.venv/bin/python -c "
import cv2, json; r = json.load(open('$S/fixture.json'))
cv2.imwrite('$S/tag_texture.png', cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, r['tag']['dictionary'])), r['tag']['id'], 600))"
seat=$(.venv/bin/python -c "import json; print(json.load(open('$S/fixture.json'))['part']['seat_shift_mm'][2])")
# The part seated: in the fixture's frame, raised by its seat.
.venv/bin/python -c "
import trimesh; m = trimesh.load('$S/model_cad.stl'); m.apply_translation((0, 0, $seat)); m.export('$O/servo_seated.stl')"
rm -rf $O/frames_tree $O/frames_fixture
$B -b -P tools/render_turntable.py -- --out $O/frames_tree --item $S/model_cad.stl:0.6,0.61,0.64:-38 --item $S/agent_model.stl:0.22,0.35,0.96:38 > $O/tree.log 2>&1
$B -b -P tools/render_turntable.py -- --out $O/frames_fixture --keep-frame --tag $S --elev 35 \
  --item $S/fixture.stl:0.92,0.92,0.94:0 --item $O/servo_seated.stl:0.85,0.35,0.2:0 > $O/fixture.log 2>&1
for n in tree fixture; do
  out=$O/servo_$([ $n = tree ] && echo scan_and_tree || echo fixture).mp4
  ffmpeg -y -loglevel error -framerate 30 -i $O/frames_$n/f%04d.png -c:v libx264 -pix_fmt yuv420p -crf 18 $out
  echo "wrote $out"
done
