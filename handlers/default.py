from manager import manager

logger = manager.logger

@manager.register("message")
async def default_handler(event):
    chat = await event.get_chat()
    sender = await event.get_sender()
    
    chat_title = getattr(chat, 'title', 'Private')
    user_id = sender.id if sender else 0
    full_name = manager.username(sender) if sender else "Unknown"
    
    logger.debug(f"default handler: chat {event.chat_id}({chat_title}) user {user_id}({full_name}) {event.text}")