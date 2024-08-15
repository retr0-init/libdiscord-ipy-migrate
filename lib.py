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

webhook_name: str = "DBF"
webhook_avatar: interactions.Absent[interactions.UPLOADABLE_TYPE] = interactions.MISSING

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
    available_webhooks: list[interactions.Webhook] = [wh for wh in webhooks if wh.name == webhook_name and wh.type == interactions.WebhookTypes.APPLICATION]
    if len(available_webhooks) == 0:
        webhook: interactions.Webhook = await dest_chan.create_webhook(name=webhook_name, avatar=webhook_avatar)
    else:
        webhook: interactions.Webhook = available_webhooks[0]
    
    return webhook

async def migrate_message(orig_msg: interactions.Message, dest_chan: interactions.GuildChannel, thread_id: Optional[int] = None) -> tuple[bool, Optional[int]]:
    """
    Migrate a message to target channel. Only supports GuildText and GuildForum

    Parameters:
        orig_msg    Message         The original message object
        dest_chan   GuildChannel    Destination channel
        thread_id   Optional[int]   (Default: None) Destination thread ID in the channel. 0 to create a new one. None if not thread.

    Return:
        Success     bool            Whether this operation is successful
        thread_id   Optional[int]   Destination thread ID. If it's not a thread, None.
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

    # Check destination channel type
    if not (isinstance(dest_chan, interactions.GuildText) or isinstance(dest_chan, interactions.GuildForum)):
        return False, None
    # Get destination channel webhook. If not present, create one.
    webhook: interactions.Webhook = await fetch_create_webhook(dest_chan=dest_chan)

    if thread_id is None:
        pass
    elif thread_id == 0:
        thread_name = channel_name
    else:
        thread = thread_id
    
    sent_msg = await webhook.send(
        content=msg_text,
        embeds=msg_embeds,
        files=msg_attachments,
        username=author_name,
        avatar_url=author_avatar.url,
        thread=thread,
        thread_name=thread_name
    )
    if isinstance(sent_msg.channel, interactions.ThreadChannel):
        output_thread_id = sent_msg.channel.id

    return True, output_thread_id

async def migrate_thread(orig_thread: interactions.ThreadChannel, dest_chan: Union[interactions.GuildText, interactions.GuildForum]) -> None:
    """
    Migrate a thread to a target channel. It's only limited to thread in GuildText and GuildForumPost types.
    """
    if not (isinstance(orig_thread, interactions.GuildForumPost) and isinstance(dest_chan, interactions.GuildForum)):
        return
    history_iterator: interactions.ChannelHistory = orig_thread.history(0)
    history_list: list[interactions.Message] = await history_iterator.flatten()
    history_list.reverse()
    parent_msg: interactions.Message = None
    thread_id: int = 0
    if isinstance(orig_thread, interactions.GuildForumPost):
        orig_thread: interactions.GuildForumPost = cast(interactions.GuildForumPost, orig_thread)
        if orig_thread.initial_post is not None:
            parent_msg = orig_thread.initial_post
    elif isinstance(orig_thread, interactions.ThreadChannel):
        if orig_thread.parent_message is not None:
            parent_msg = orig_thread.parent_message
    else:
        return
    
    # Create thread
    if parent_msg is None:
        webhook = await fetch_create_webhook(dest_chan=dest_chan)
        sent_msg = await webhook.send(
            content="This message has been deleted by original author",
            thread=None,
            thread_name=orig_thread.name
        )
        thread_id = sent_msg.channel.id
    for i, msg in enumerate(history_list):
        if i == 0 and parent_msg is not None and msg != parent_msg:
            ok, thread_id = await migrate_message(parent_msg, dest_chan, thread_id)
        ok, thread_id = await migrate_message(msg, dest_chan, thread_id)
        if not ok and thread_id is None:
            break

async def migrate_channel(orig_chan: Union[interactions.GuildText, interactions.GuildForum], dest_chan: Union[interactions.GuildText, interactions.GuildForum], client: interactions.Client) -> None:
    """
    Migrate a channel to another destination channel. It's only limited to GuildText and GuildForum.
    """
    ...
    if isinstance(orig_chan, interactions.GuildForum):
        if not isinstance(dest_chan, interactions.GuildForum):
            return
        orig_chan: interactions.GuildForum = cast(interactions.GuildForum, orig_chan)
        _archived_posts = await client.http.list_public_archived_threads(orig_chan.id)
        archived_posts_id: list[int] = [int(_["id"]) for _ in _posts["threads"]]
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
        raise NotImplementedError("GuildText channel migration not implemented yet")