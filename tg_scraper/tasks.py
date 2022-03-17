import asyncio
import datetime
import itertools
import logging
import time

import aioitertools
from faker import Faker
from telethon.errors.rpcerrorlist import *
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest, JoinChannelRequest, \
    LeaveChannelRequest, DeleteChannelRequest, GetParticipantRequest
from tortoise.expressions import F


from . import keyboards, states
from .bot import dispatcher
from .models import Account, Group, Settings
from .tg import TgClient, IsBroadcastChannelError
from .utils import exc_to_msg, relative_sleep, get_proxies


logger = logging.getLogger(__name__)


class RunState:

    def __init__(self, limit):
        self.limit = limit
        self.added = 0
        self.users_processed = set()

    @property
    def limit_reached(self):
        return self.added >= self.limit


def user_valid(user, last_seen):
    return not any([user.bot, user.deleted, user.scam]) and user_status_valid(user, last_seen)


def user_status_valid(user, filter):
    if filter:
        last_seen = user_last_seen(user)
        if last_seen is not None:
            return last_seen <= filter
        return False
    return True


def user_last_seen(user):
    days_ago = 365
    status = user.status
    if status:
        name = status.to_dict()['_']
        days_map = {
            'UserStatusOnline': 0, 'UserStatusRecently': 1,
            'UserStatusLastWeek': 7, 'UserStatusLastMonth': 30,
        }
        if name in days_map:
            days_ago = days_map[name]
    return days_ago


async def update_name(client):
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))


async def sign_in(client, chat_id, queue):
    bot = dispatcher.bot
    acc = client.account
    code = None
    while True:
        try:
            if code:
                await client.sign_in(acc.phone, code)
                return True
            else:
                await client.send_code_request(acc.phone, force_sms=True)
        except (ApiIdInvalidError, PhoneNumberBannedError, FloodWaitError, PhoneNumberUnoccupiedError) as e:
            await bot.send_message(chat_id, exc_to_msg(e), disable_web_page_preview=True)
            if type(e) in (ApiIdInvalidError, PhoneNumberBannedError):
                await acc.delete()
                await bot.send_message(chat_id, 'Account has been deleted.')
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            msg = ('{}\n'
                   'You can reenter code.\n'
                   '<i>Keep in mind that after several attempts Telegram might'
                   ' temporarily block account from signing in .</i>').format(exc_to_msg(e))
        else:
            msg = ('Code was sent to <b>{}</b>\n'
                   'Please divide it with whitespaces, like: <i>41 9 78</i>').format(acc.safe_name)
        await states.Scrape.enter_code.set()
        await bot.send_message(chat_id, msg, reply_markup=keyboards.code_request())
        answer = await queue.get()
        queue.task_done()
        if answer == 'resend':
            code = None
        elif answer == 'skip':
            return
        else:
            code = answer


async def on_group_error(error, group):
    try:
        raise error
    except InviteHashExpiredError:
        msg = 'Invite link has expired.'
    except (InviteHashInvalidError, ChannelInvalidError, ChatIdInvalidError,
            ChatInvalidError, PeerIdInvalidError, ValueError):
        msg = 'Group doesn\'t exist or join link is not valid.'
    except (ChatWriteForbiddenError, ChatAdminRequiredError):
        msg = 'Adding users is not allowed.'
    except IsBroadcastChannelError:
        msg = 'It is broadcast channel and cannot be used.'
    group.enabled = False
    group.details = msg
    await group.save()
    msg = '♦️<i>{}</i> Error. {}'.format(group.get_name(), msg)
    return msg


async def worker(accounts, group_to, group_from, state: RunState, settings):
    # TODO: MAke sure settings refresh if changed when task running
    while accounts:
        acc, proxy = accounts.pop(0)
        start = time.time()
        # TODO: Fix algo
        try:
            async with TgClient(acc, store_session=False, proxy=proxy) as client:
                if not await client.is_user_authorized():
                    logger.info('Account %s is not authenticated. Deleting from db.', acc.name)
                    await acc.delete()
                    continue
                await update_name(client)
                await client.clear_channels(free_slots=2)
                await client.clear_blocked()
                try:
                    to = await client.join_group(group_to.link)
                except (ChannelPrivateError, UsernameInvalidError):
                    continue
                except (InviteHashExpiredError, InviteHashInvalidError,
                        ChannelInvalidError, IsBroadcastChannelError, ValueError) as err:
                    return await on_group_error(err, group_to)
                await relative_sleep(5)
                try:
                    from_ = await client.join_group(group_from.link)
                except (ChannelPrivateError, UsernameInvalidError):
                    accounts.append((acc, proxy))
                    continue
                except (InviteHashExpiredError, InviteHashInvalidError,
                        ChannelInvalidError, IsBroadcastChannelError, ValueError) as err:
                    accounts.append((acc, proxy))
                    return await on_group_error(err, group_from)
                try:
                    users = await client.get_participants(from_)
                except (ChatAdminRequiredError, GetParticipantRequest, ValueError) as err:
                    return await on_group_error(err, from_)
                group_from.users_count = len(users)
                await group_from.save()
                for user in filter(lambda x: user_valid(x, settings.last_seen), users):
                    user_id = user.id
                    if user_id in state.users_processed:
                        continue
                    try:
                        # TODO: exception handling and checking if invite success
                        res = await client.invite_to_group(user, to)
                    # TODO: Check if all exceptions present
                    except (ChannelInvalidError, ChatIdInvalidError, ChatInvalidError, PeerIdInvalidError,
                            ChatAdminRequiredError) as err:
                        return await on_group_error(err, group_to)
                    except (InputUserDeactivatedError, UserBannedInChannelError, UserChannelsTooMuchError,
                            UserKickedError, UserPrivacyRestrictedError, UserIdInvalidError,
                            UserNotMutualContactError, UserAlreadyParticipantError):
                        pass
                    except (ChannelPrivateError, ChatWriteForbiddenError):
                        break
                    except (PeerFloodError, FloodWaitError) as e:
                        seconds = getattr(e, 'seconds', 20)
                        await relative_sleep(seconds)
                    else:
                        # TODO: implement proxy reused
                        await acc.incr_invites()
                        state.added += 1
                        if state.limit_reached:
                            return
                    state.users_processed.add(user_id)
                    if not acc.can_invite:
                        dt = datetime.datetime.now() + datetime.timedelta(days=settings.limit_reset_days)
                        acc.invites_reset_at = dt
                        await acc.save()
                        break
                    await relative_sleep(8)
                else:
                    msg = '🔷 <i>{}</i> group has been processed.'.format(group_from.name)
                    return msg
                end = time.time()
                delay = settings.join_delay - (end - start)
                if delay > 0:
                    await relative_sleep(delay)
        except AuthKeyDuplicatedError:
            logger.info('Account %s cannot be used anymore.', acc.name)
            # await client.save_session()
        except UserDeactivatedBanError:
            logger.info('Account %s has been banned. Deleting from db.', acc.name)
            await acc.delete()


async def scrape(chat_id, queue: asyncio.Queue):
    bot = dispatcher.bot
    await bot.send_message(chat_id, 'Task started. You can stop it at any moment with /stop command.')
    settings = await Settings.get()
    accounts = list(await Account.filter(auto_created=True, invites_sent__lt=F('invites_max')))
    if settings.enable_proxy:
        proxies = get_proxies()
        accounts = list(zip(accounts, proxies))
    print(accounts)
    max_invites = sum(acc.invites_left for acc, proxy in accounts)
    accs_loaded = len(accounts)
    await states.Scrape.add_limit.set()
    msg = 'Please enter max number of users to add, <b>{} max</b>.'.format(max_invites)
    await bot.send_message(chat_id, msg, reply_markup=keyboards.max_btn(max_invites))
    limit = await queue.get()
    queue.task_done()
    limit = min(max_invites, limit)
    target = await Group.get(is_target=True)
    sources = await Group.filter(enabled=True, is_target=False)
    state = RunState(limit)
    tasks = []
    task_name = str(chat_id)
    for group in sources:
        task = asyncio.create_task(worker(accounts, target, group, state, settings), name=task_name)
        tasks.append(task)
    animation = animation_frames()
    logs = []
    message = None
    while tasks:
        done, tasks = await asyncio.wait(tasks, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            msg = task.result()
            if msg and msg not in logs:
                logs.append(msg)
        if not tasks:
            status = '☘ Completed ☘'
        else:
            status = 'Running tasks'
        msg = ('<b>{status}</b>\n\n'
               'Tasks (groups): {tasks}\n'
               'Sessions: {accs_used}/{accs_total}\n'
               'Users processed: {processed}\n'
               'Users added: {added}\n\n'
               '{loading}\n\n'
               '<i>Logs:</i>\n\n'
               '{logs}\n').format(
            status=status,
            tasks=len(tasks),
            accs_used=accs_loaded - len(accounts),
            accs_total=accs_loaded,
            processed=len(state.users_processed),
            added=state.added,
            loading=next(animation),
            logs='\n'.join(logs)
        )
        if not message:
            message = await bot.send_message(chat_id, msg, disable_web_page_preview=True)
        else:
            message = await message.edit_text(msg, disable_web_page_preview=True)
    await states.Menu.main.set()
    await bot.send_message(chat_id, 'Main', reply_markup=keyboards.main_menu())
    # TODO: Cancel handler with message


def animation_frames():
    frame = '▂▂▃▃▄▄▅▅▆▆▇▇██▇▇▆▆▅▅▄▄▃▃▂▂▁▁'
    frame = list(frame)
    while True:
        yield ''.join(frame)
        frame.insert(0, frame.pop())


# def animation():


async def show_loading(message):
    text = message.text
    async for sym in aioitertools.cycle('⬖⬘⬗⬙'):
        msg = '{} {}'.format(text, sym)
        print(msg)
        message = await message.edit_text(msg)
        await asyncio.sleep(1)
