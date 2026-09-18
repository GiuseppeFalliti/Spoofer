import os
base=r'C:\Users\Giuseppe Falliti\Desktop\Spoofer'
with open(os.path.join(base,'test_write.txt'),'w') as f:
    f.write('hello')
print('OK')
