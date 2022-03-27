基本功能：

* 入群验证：将机器人加入群内，并且设置为管理员后，具备入群验证的基本功能

    当用户加入群后，机器人会删除入群信息，并且发出验证信息。 <br />
    验证信息包括：
    
    - 欢迎文本
    - 验证按钮
    - 管理员操作按钮 
        - ✔️ 直接允许，用户跳过验证环节
        - ❌ 踢掉用户，用户列入黑名单30天

包括命令:

- /k 踢掉发信息的人
- /id 获取用户信息，reply 信息则会返回发信人的详细信息
- /asr 识别音频内文本
- /tts 转换文本为音频

配置文件 main.ini

```ini
[default]
debug = false

[telegram]
token = TG 的 BOT TOKEN

[tts]
token = OFFICE 的 TOKEN

[asr]
tx_id =  腾讯云ID
tx_key = 腾讯云KEY
users = 指定TG用户ID，如果不指定，则无限制
```