'''
libdiscord-ipy-migrate

Copyright (C) 2024  __retr0.init__

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''
import interactions
from typing import Optional, cast, Union

"Highly recommended - we suggest providing proper debug logging"
from src import logutil

import os
"Change this if you'd like - this labels log messages for debug mode"
logger = logutil.init_logger(os.path.basename(__file__))

webhook_name: str = "DBF"
webhook_avatar: interactions.Absent[interactions.UPLOADABLE_TYPE] = interactions.MISSING

__MESSAGE_LEN_LIMIT: int = 2000

async def flatten_history_iterator(history: interactions.ChannelHistory, reverse: bool = False) -> list[interactions.Message]:
    """
    Flatten the ChannelHistory iteractor while handling all kinds of errors

    Parameters:
        history         ChannelHistory  Iteractor
        reverse         bool            (Default False) Whether to output the list from begining to end
    
    Return:
        message_list    list[Message]   List of messages in the list
    """
    ret_list: list[interactions.Message] = []
    while True:
        try:
            msg = await history.__anext__()
            ret_list.append(msg)
        except StopAsyncIteration:
            break
        except interactions.errors.HTTPException as e:
            try:
                match int(e.code):
                    case 50083:
                        """Operation in archived thread"""
                        break
                    case 10003:
                        """Unknown channel"""
                        break
                    case 10008:
                        """Unknown message"""
                        pass
                    case 50001:
                        """No Access"""
                        break
                    case 50013:
                        """Lack permission"""
                        break
                    case 50021:
                        """Cannot execute on system message"""
                        pass
                    case 160005:
                        """Thread is locked"""
                        pass
                    case _:
                        """Default"""
                        pass
            except ValueError:
                pass
        except Exception:
            pass
    if reverse:
        ret_list.reverse()
    return ret_list


async def fetch_create_webhook(dest_chan: interactions.WebhookMixin) -> interactions.Webhook:
    """
    Fetch the webhook from a destination channel. If not exist, create one.

    Parameters:
        dest_chan   WebhookMixin    Destination channel

    Return:
        webhook     Webhook         Fetched webhook
    """
    dest_chan: interactions.WebhookMixin = cast(interactions.WebhookMixin, dest_chan)
    webhooks: list[interactions.Webhook] = await dest_chan.fetch_webhooks()
    available_webhooks: list[interactions.Webhook] = [wh for wh in webhooks if wh.name == webhook_name]
    if len(available_webhooks) == 0:
        webhook: interactions.Webhook = await dest_chan.create_webhook(name=webhook_name, avatar=webhook_avatar)
    else:
        webhook: interactions.Webhook = available_webhooks[0]
    
    return webhook

def convert_poll_to_message(poll: interactions.Poll) -> str:
    """
    Convert current poll Q&A with results to postable message text.

    Parameters:
        poll    Poll    Discord Poll object

    Return:
        message str     Converted message string
    """
    def poll_media_to_str(poll_media: interactions.PollMedia) -> str:
        ret: str = ""
        if isinstance(poll_media, interactions.PollMedia):
            poll_media = poll_media.to_dict()
        if 'emoji' in poll_media.keys() and poll_media['emoji']:
            if 'id' in poll_media['emoji']:
                ret += f"<:{poll_media['emoji']['name']}:{poll_media['emoji']['id']}>"
            else:
                ret += poll_media["emoji"]['name']
        if 'text' in poll_media.keys():
            ret += " " + poll_media['text']
        return ret
    
    question_str: str = poll_media_to_str(poll.question)
    answers: list[str] = [poll_media_to_str(pa.poll_media) for pa in poll.answers]
    if poll.results:
        results: list[int] = [ac.count for ac in poll.results.answer_counts]
        answers = (f"{i:04d} - {j}" for i, j in zip(results, answers))
    final_str: str = question_str + "\n" + "\n".join(answers)
    if poll.results:
        final_str = f"(Poll finished) {final_str}"

    return final_str

async def migrate_message(orig_msg: interactions.Message, dest_chan: interactions.GuildChannel, thread_id: Optional[int] = None) -> tuple[bool, Optional[int], Optional[interactions.Message]]:
    """
    Migrate a message to target channel. Only supports GuildText and GuildForum

    Parameters:
        orig_msg    Message             The original message object
        dest_chan   GuildChannel        Destination channel
        thread_id   Optional[int]       (Default: None) Destination thread ID in the channel. 0 to create a new one. None if not thread.

    Return:
        Success     bool                Whether this operation is successful
        thread_id   Optional[int]       Destination thread ID. If it's not a thread, None.
        dest_msg    Optional[Message]   The sent message
    """
    # Initialise variables to be used
    msg_text: str = orig_msg.content
    msg_embeds: list[interactions.Embed] = orig_msg.embeds
    msg_attachments: list[interactions.Asset] = orig_msg.attachments
    msg_author: interactions.User = orig_msg.author
    author_avatar: interactions.Asset = msg_author.display_avatar
    author_name: str = msg_author.display_name
    channel_name: str = orig_msg.channel.name

    thread: interactions.Snowflake_Type = None
    thread_name: Optional[str] = None
    output_thread_id: Optional[int] = None
    available_stickers: Optional[list[interactions.Sticker]] = None

    # Check destination channel type
    if not (isinstance(dest_chan, interactions.GuildText) or isinstance(dest_chan, interactions.GuildForum)):
        return False, None
    # Get destination channel webhook. If not present, create one.
    webhook: interactions.Webhook = await fetch_create_webhook(dest_chan=dest_chan)

    # Get the message the current message is replying to
    reply_to: Optional[interactions.Message] = orig_msg.get_referenced_message()
    replied_text: str = ""
    if reply_to is not None and any(reply_to.type == _ for _ in [interactions.MessageType.DEFAULT, interactions.MessageType.REPLY, interactions.MessageType.THREAD_STARTER_MESSAGE]):
        if reply_to.poll:
            msgs_reply_to: list[str] = ["> " + msg_reply_to for msg_reply_to in convert_poll_to_message(reply_to.poll).splitlines(False)]
        else:
            msgs_reply_to: list[str] = ["> " + msg_reply_to for msg_reply_to in reply_to.content.splitlines(False)]
        replied_text: str = f"> **{reply_to.author.display_name}** said:\n" + '\n'.join(msgs_reply_to)
    msg_text = replied_text + "\n" + msg_text

    if msg_attachments:
        attachment_url: str = "\n".join(i.url for i in msg_attachments)
        msg_text = attachment_url + "\n" + msg_text
    
    if orig_msg.sticker_items:
        all_stickers = await dest_chan.guild.fetch_all_custom_stickers()
        available_stickers = [sticker for sticker in all_stickers if any(sticker.id == i.id or sticker.name == i.name for i in orig_msg.sticker_items)]
        if orig_msg.sticker_items and len(available_stickers) < len(orig_msg.sticker_items):
            msg_text = f"Sticker {','.join(i.name for i in orig_msg.sticker_items if not any(i.id == s.id or i.name == s.name for s in available_stickers))} not available\n" + msg_text
        for s in available_stickers:
            msg_text = f"{s.url}\n" + msg_text

    if orig_msg.poll:
        msg_text = convert_poll_to_message(orig_msg.poll) + "\n" + msg_text

    if thread_id is None:
        pass
    elif thread_id == 0:
        thread_name = channel_name
    else:
        thread = thread_id
    
    # Split send the message if the length exceeds limit
    sent_msg: Optional[int] = None
    for text in (msg_text[0 + i : __MESSAGE_LEN_LIMIT + i] for i in range(0, len(msg_text), __MESSAGE_LEN_LIMIT)):
        try:
            sent_msg = await webhook.send(
                content=text,
                embeds=msg_embeds,
                username=author_name,
                avatar_url=author_avatar.url,
                reply_to=sent_msg,
                allowed_mentions=interactions.AllowedMentions.none(),
                wait=True,
                thread=thread,
                thread_name=thread_name
            )
        except interactions.errors.HTTPException as e:
            if e.code is None:
                reason_text: str = "of unknown error code"
            else:
                match int(e.code):
                    case 50083:
                        """Operation in archived thread"""
                        reason_text: str = "This thread is archived"
                    case 10003:
                        """Unknown channel"""
                        reason_text: str = "The channel is unknown"
                        return
                    case 10008:
                        """Unknown message"""
                        reason_text: str = "The message is unknown"
                        return
                    case 50001:
                        """No Access"""
                        reason_text: str = "The bot has no access"
                        return
                    case 50006:
                        """Cannot send an empty message"""
                        reason_text: str = "Cannot send an empty message"
                    case 50013:
                        """Lack permission"""
                        reason_text: str = "The bot lacks the write permission to this channel"
                        return
                    case 50021:
                        """Cannot execute on system message"""
                        reason_text: str = "This thread is archived"
                        pass
                    case 160005:
                        """Thread is locked"""
                        reason_text: str = "This thread is locked"
                        pass
                    case _:
                        """Default"""
                        reason_text: str = f"Unknown error {e.code}"
                        pass
            sent_msg = await webhook.send(
                content=f"Message {orig_msg.jump_url} {orig_msg.id} cannot be migrated because {reason_text}",
                username=author_name,
                avatar_url=author_avatar.url,
                wait=True,
                thread=thread,
                thread_name=thread_name
            )
        if sent_msg and isinstance(sent_msg.channel, interactions.ThreadChannel):
            output_thread_id = sent_msg.channel.id

    return True, output_thread_id, sent_msg

def is_empty_message(msg: interactions.Message) -> bool:
    return not any((msg.content, msg.embeds, msg.poll, msg.reactions, msg.sticker_items))

async def migrate_thread(orig_thread: interactions.ThreadChannel, dest_chan: Union[interactions.GuildText, interactions.GuildForum]) -> None:
    """
    Migrate a thread to a target channel. It's only limited to thread in GuildText and GuildForumPost types.
    """
    if not ((isinstance(orig_thread, interactions.GuildForumPost) and isinstance(dest_chan, interactions.GuildForum)) or \
        ((isinstance(orig_thread, interactions.GuildPublicThread) and not isinstance(orig_thread, interactions.GuildForumPost)) and isinstance(dest_chan, interactions.GuildText))):
        return
    history_iterator: interactions.ChannelHistory = orig_thread.history(0)
    history_list: list[interactions.Message] = await flatten_history_iterator(history_iterator, reverse=True)
    parent_msg: interactions.Message = None
    thread_id: int = 0
    if isinstance(orig_thread, interactions.GuildForumPost):
        orig_thread: interactions.GuildForumPost = cast(interactions.GuildForumPost, orig_thread)
        if orig_thread.initial_post is not None:
            parent_msg = orig_thread.initial_post
    elif isinstance(orig_thread, interactions.GuildPublicThread) and not isinstance(orig_thread, interactions.GuildForumPost):
        if orig_thread.parent_message is not None:
            parent_msg = orig_thread.parent_message
    else:
        return
    
    # Create thread
    if parent_msg is None:
        webhook = await fetch_create_webhook(dest_chan=dest_chan)
        if isinstance(dest_chan, interactions.GuildForum):
            sent_msg = await webhook.send(
                content="This message has been deleted by original author",
                thread=None,
                thread_name=orig_thread.name,
                wait=True
            )
            thread_id = sent_msg.channel.id
        elif isinstance(dest_chan, interactions.GuildText):
            sent_msg = await webhook.send(
                content="This message has been deleted by original author",
                wait=True
            )
            sent_thread = await sent_msg.create_thread(
                name=orig_thread.name,
                reason="Message migration"
            )
            thread_id = sent_thread.id
    for i, msg in enumerate(history_list):
        if i == 0:
            if isinstance(orig_thread, interactions.GuildForumPost) and parent_msg is not None and msg != parent_msg:
                ok, thread_id, _ = await migrate_message(parent_msg, dest_chan, thread_id)
            elif (isinstance(orig_thread, interactions.GuildPublicThread) and not isinstance(orig_thread, interactions.GuildForumPost)) and parent_msg is not None:
                ok, _, sent_msg = await migrate_message(parent_msg, dest_chan)
                sent_thread = await sent_msg.create_thread(
                    name = orig_thread.name,
                    reason = "Message migration"
                )
                thread_id = sent_thread.id
        if is_empty_message(msg):
            continue
        ok, thread_id, _ = await migrate_message(msg, dest_chan, thread_id)
        if not ok and thread_id is None:
            break

async def migrate_channel(orig_chan: Union[interactions.GuildText, interactions.GuildForum], dest_chan: Union[interactions.GuildText, interactions.GuildForum], client: interactions.Client) -> None:
    """
    Migrate a channel to another destination channel. It's only limited to GuildText and GuildForum.
    """
    if isinstance(orig_chan, interactions.GuildForum):
        if not isinstance(dest_chan, interactions.GuildForum):
            return
        orig_chan: interactions.GuildForum = cast(interactions.GuildForum, orig_chan)
        _archived_posts = await client.http.list_public_archived_threads(orig_chan.id)
        archived_posts_id: list[int] = [int(_["id"]) for _ in _archived_posts["threads"]]
        archived_posts_id.reverse()
        for i in archived_posts_id:
            post = await orig_chan.fetch_post(id=i)
            await migrate_thread(post, dest_chan)
        active_posts: list[interactions.GuildForumPost] = await orig_chan.fetch_posts()
        active_posts.reverse()
        for post in active_posts:
            await migrate_thread(post, dest_chan)
    elif isinstance(orig_chan, interactions.GuildText):
        if not isinstance(dest_chan, interactions.GuildText):
            return
        orig_chan: interactions.GuildText = cast(interactions.GuildText, orig_chan)
        messages: list[interactions.Message] = await flatten_history_iterator(orig_chan.history(0), reverse=True)
        for msg in messages:
            if msg.thread:
                await migrate_thread(msg.thread, dest_chan)
            else:
                await migrate_message(msg, dest_chan)
