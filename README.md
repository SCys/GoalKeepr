TG 机器人

https://github.com/SCys/GoalKeepr

翻译感谢 77 老师。

将机器人加入群内，并且设置为管理员(提供相应的权限)后，具备入群验证的基本功能。

当用户加入群后，机器人会删除入群信息，并且发出验证信息。

验证信息包括：

- 欢迎文本
- 验证按钮
- 管理员操作按钮
  - ✔️ 直接允许，用户跳过验证环节
  - ❌ 踢掉用户，用户列入黑名单 30 天

包括命令:

<pre>
k - 踢掉发信息的人 kicks off the person who sent the message
id - 获取用户信息，reply 信息则会返回发信人的详细信息 gets the user information, reply message returns the sender details
asr - 识别音频内文本 recognizes text within audio
tts - 转换文本为音频 convert text to audio
shorturl - 压缩 URL,支持多条 URL 同时压缩，每条之间换行即可 compress URLs, support multiple URLs at the same time, just line break between each one
tr - 将输入的文本翻译为中文 translate the input text into Chinese
</pre>

配置文件 main.ini

```ini
[default]
debug = false

[telegram]
token = TG 的 BOT TOKEN

[asr]
tx_id =  腾讯云ID
tx_key = 腾讯云KEY
users = 指定TG用户ID，如果不指定，则无限制
```
