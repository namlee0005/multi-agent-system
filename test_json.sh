/home/ben/.npm-global/bin/claude --print --output-format json --permission-mode bypassPermissions "Write a python script called hello.py that prints hello world. Use your native tool." > test_out.json
cat test_out.json | grep -i "hello"
