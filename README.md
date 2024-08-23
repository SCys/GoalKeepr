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
k - 踢掉发信息的人 Kick the person who sent the message.
sb - 将发送信息的人放入黑名单，会清理此人之前发出的所有信息 Put the person who sent the message into the blacklist, and clean up all the information sent by this person before.
id - 获取用户信息，信息则会返回发信人的详细信息 Get user information, information will return the detailed information of the sender
asr - 识别音频内文本 Recognizes text within audio. Powerby openai whisper-small(multi languages).
tts - 转换文本为音频 Convert text to audio
tr - 将输入的文本翻译为中文 translate the input text into Chinese
image - 通过文本生成图像 Generate images through text.Support English. Chinese will translate to English.
sdxl - 通过文本生成图像 Generate images through text(Power by cloudflare, use SDXL)
chat - 支持上下文的聊天功能，允许配置相关参数，详情请输入 Chat function that supports context, allows configuration of related parameters, please enter for details
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

[sd_api]
endpoint = https://api.snowdusk.me
```
