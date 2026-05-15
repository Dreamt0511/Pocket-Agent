1.这个可以打开一个文件浏览目录，直接浏览访问termux中的数据

am start -a android.intent.action.VIEW -d "content://com.android.externalstorage.documents/root/primary"


更新代码
cd /storage/emulated/0/手机agent开发/Pocket-Agent
git pull

运行命令
python /storage/emulated/0/手机agent开发/Pocket-Agent/main.py

或者（这个能解决环境变量问题）
cd /storage/emulated/0/手机agent开发/Pocket-Agent && source .env && python main.py