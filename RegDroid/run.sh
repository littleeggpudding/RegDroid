nohup python start.py \
  -base_app_path ./App/AnkiDroid-old.apk \
  -new_app_dir ./test2 \
  -output test-results \
  -testcase_count 3 \
  -event_num 20 \
  > start.log 2>&1 &


 nohup python3 start.py \
  -base_app_path ./App/6.3.1.apk \
  -new_app_dir ./OmniNotes/ \
  -output test-results \
  -testcase_count 30 \
  -event_num 110 \
  -emulator_name Android8.0 \
  > start.log 2>&1 &
