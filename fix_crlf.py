import os
with open('start.sh', 'rb') as f:
    content = f.read()
content = content.replace(b'\r\n', b'\n')
with open('start.sh', 'wb') as f:
    f.write(content)
