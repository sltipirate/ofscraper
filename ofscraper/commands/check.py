import asyncio
import inspect
import logging
import queue
import re
import threading
import time
import traceback

import arrow

import ofscraper.api.archive as archived
import ofscraper.api.highlights as highlights
import ofscraper.api.messages as messages_
import ofscraper.api.paid as paid_
import ofscraper.api.pinned as pinned
import ofscraper.api.profile as profile
import ofscraper.api.timeline as timeline
import ofscraper.api.labels as labels
import ofscraper.classes.posts as posts_
import ofscraper.classes.sessionbuilder as sessionbuilder
import ofscraper.classes.table as table
import ofscraper.commands.manual as manual
import ofscraper.db.operations as operations
import ofscraper.download.downloadnormal as downloadnormal
import ofscraper.models.selector as selector
import ofscraper.utils.args.read as read_args
import ofscraper.utils.args.write as write_args
import ofscraper.utils.auth.request as auth_requests
import ofscraper.utils.cache as cache
import ofscraper.utils.console as console_
import ofscraper.utils.constants as constants
import ofscraper.utils.settings as settings
import ofscraper.utils.system.network as network
from ofscraper.download.common.common import textDownloader
from ofscraper.utils.context.run_async import run

log = logging.getLogger("shared")
console = console_.get_shared_console()
ROW_NAMES = (
    "Number",
    "Download_Cart",
    "UserName",
    "Downloaded",
    "Unlocked",
    "Times_Detected",
    "Length",
    "Mediatype",
    "Post_Date",
    "Post_Media_Count",
    "Responsetype",
    "Price",
    "Post_ID",
    "Media_ID",
    "Text",
)
ROWS = []
app = None


def process_download_cart():
    while True:
        global app
        while app and not app.row_queue.empty():
            if process_download_cart.counter == 0:
                if not network.check_cdm():
                    log.info(
                        "error was raised by cdm checker\ncdm will not be check again\n\n"
                    )
                else:
                    log.info("cdm checker was fine\ncdm will not be check again\n\n")
                # should be done once before downloads
                log.info("Getting Models")

            process_download_cart.counter = process_download_cart.counter + 1
            log.info("Getting items from queue")
            try:
                row, key = app.row_queue.get()
                restype = row[app.row_names.index("Responsetype")].plain
                username = app.row_names.index("UserName")
                post_id = app.row_names.index("Post_ID")
                media_id = app.row_names.index("Media_ID")
                url = None
                if restype == "message":
                    url = constants.getattr("messageTableSPECIFIC").format(
                        row[username].plain, row[post_id].plain
                    )
                elif restype in {"pinned", "timeline", "archived"}:
                    url = f"{row[post_id]}"
                elif restype == "highlights":
                    url = constants.getattr("storyEP").format(row[post_id].plain)
                elif restype == "stories":
                    url = constants.getattr("highlightsWithAStoryEP").format(
                        row[post_id].plain
                    )
                else:
                    log.info("URL not supported")
                    continue
                log.info(f"Added url {url}")
                log.info("Sending URLs to OF-Scraper")
                url_dicts= manual.process_urls(urls=[url])
                # None for stories and highlights
                matchID = int(row[media_id].plain)
                medialist = list(
                    filter(
                        lambda x: x.id == matchID if x.id else None,
                        list(media_dict.values())[0],
                    )
                )
                if settings.get_mediatypes() == ["Text"]:
                    textDownloader(post_dict.values(), username=username)
                elif len(medialist) > 0 and len(settings.get_mediatypes()) > 1:
                    media = medialist[0]
                    model_id = media.post.model_id
                    username = model_id = media.post.username
                    args = read_args.retriveArgs()
                    args.usernames = set([username])
                    write_args.setArgs(args)
                    selector.all_subs_helper()
                    log.info(
                        f"Downloading individual media ({media.filename}) to disk for {username}"
                    )
                    operations.table_init_create(model_id=model_id, username=username)

                    textDownloader(post_dict.values(), username=username)

                    values = downloadnormal.process_dicts(username, model_id, [media])
                    if values == None or values[-1] == 1:
                        raise Exception("Download is marked as skipped")
                else:
                    raise Exception("Issue getting download")

                log.info("Download Finished")
                app.update_cell(key, "Download_Cart", "[downloaded]")
                app.update_cell(key, "Downloaded", True)

            except Exception as E:
                app.update_downloadcart_cell(key, "[failed]")
                log.traceback_(E)
                log.traceback_(traceback.format_exc())
        time.sleep(10)


def checker():
    args = read_args.retriveArgs()
    if args.command == "post_check":
        post_checker()
    elif args.command == "msg_check":
        message_checker()
    elif args.command == "paid_check":
        purchase_checker()
    elif args.command == "story_check":
        stories_checker()


def post_checker():
    ROWS = post_check_helper()
    start_helper(ROWS)


@run
async def post_check_helper():
    user_dict = {}
    links = list(url_helper())
    async with sessionbuilder.sessionBuilder(backend="httpx") as c:
        for ele in links:
            name_match = re.search(
                f"onlyfans.com/({constants.getattr('USERNAME_REGEX')}+$)", ele
            )
            name_match2 = re.search(f"^{constants.getattr('USERNAME_REGEX')}+$", ele)

            if name_match:
                user_name = name_match.group(1)
                log.info(f"Getting Full Timeline for {user_name}")
                model_id = profile.get_id(user_name)
            elif name_match2:
                user_name = name_match2.group(0)
                model_id = profile.get_id(user_name)
            else:
                continue
            if user_dict.get(user_name):
                continue
            areas = read_args.retriveArgs().check_area
            user_dict[user_name] = user_dict.get(user_name) or []

            await operations.table_init_create(username=user_name, model_id=model_id)
            if "Timeline" in areas:
                oldtimeline = cache.get(f"timeline_check_{model_id}", default=[])
                if len(oldtimeline) > 0 and not read_args.retriveArgs().force:
                    user_dict[user_name].extend(oldtimeline)
                else:
                    data = await timeline.get_timeline_posts(
                        model_id, user_name, forced_after=0, c=c
                    )
                    user_dict[user_name].extend(data)
                    cache.set(
                        f"timeline_check_{model_id}",
                        data,
                        expire=constants.getattr("DAY_SECONDS"),
                    )
            if "Archived" in areas:
                oldarchive = cache.get(f"archived_check_{model_id}", default=[])
                if len(oldarchive) > 0 and not read_args.retriveArgs().force:
                    user_dict[user_name].extend(oldarchive)
                else:
                    data = await archived.get_archived_posts(
                        model_id, user_name, forced_after=0, c=c
                    )
                    user_dict[user_name].extend(data)
                    cache.set(
                        f"archived_check_{model_id}",
                        data,
                        expire=constants.getattr("DAY_SECONDS"),
                    )
            if "Pinned" in areas:
                oldpinned = cache.get(f"pinned_check_{model_id}", default=[])
                if len(oldpinned) > 0 and not read_args.retriveArgs().force:
                    user_dict[user_name].extend(oldpinned)
                else:
                    data = await pinned.get_pinned_posts(model_id, c=c)
                    user_dict[user_name].extend(data)
                    cache.set(
                        f"pinned_check_{model_id}",
                        data,
                        expire=constants.getattr("DAY_SECONDS"),
                    )

            cache.close()

            # individual links
            for ele in list(
                filter(
                    lambda x: re.search(
                        f"onlyfans.com/{constants.getattr('NUMBER_REGEX')}+/{constants.getattr('USERNAME_REGEX')}+$",
                        x,
                    ),
                    links,
                )
            ):
                name_match = re.search(
                    f"/({constants.getattr('USERNAME_REGEX')}+$)", ele
                )
                num_match = re.search(f"/({constants.getattr('NUMBER_REGEX')}+)", ele)
                if name_match and num_match:
                    user_name = name_match.group(1)
                    post_id = num_match.group(1)
                    model_id = profile.get_id(user_name)
                    log.info(f"Getting individual link for {user_name}")
                    if not user_dict.get(user_name):
                        user_dict[name_match.group(1)] = {}
                    data = timeline.get_individual_post(post_id)
                    user_dict[user_name] = user_dict[user_name] or []
                    user_dict[user_name].append(data)

    ROWS = []
    for user_name in user_dict.keys():
        downloaded = await get_downloaded(user_name, model_id, True)
        posts = list(
            map(lambda x: posts_.Post(x, model_id, user_name), user_dict[user_name])
        )
        await operations.make_post_table_changes(
            posts, model_id=model_id, username=user_name
        )
        media = await process_post_media(user_name, model_id,posts)
        ROWS.extend(row_gather(media, downloaded, user_name))
    return ROWS


def reset_url():
    # clean up args once check modes are ready to launch
    args = read_args.retriveArgs()
    argdict = vars(args)
    if argdict.get("url"):
        read_args.retriveArgs().url = None
    if argdict.get("file"):
        read_args.retriveArgs().file = None
    if argdict.get("username"):
        read_args.retriveArgs().usernames = None
    write_args.setArgs(args)


def set_count(ROWS):
    for count, ele in enumerate(ROWS):
        ele[0] = count + 1


def start_helper(ROWS):
    reset_url()
    set_count(ROWS)
    network.check_cdm()
    thread_starters(ROWS)


def message_checker():
    ROWS = message_checker_helper()
    start_helper(ROWS)


@run
async def message_checker_helper():
    links = list(url_helper())
    ROWS = []
    async with sessionbuilder.sessionBuilder(backend="httpx") as c:
        for item in links:
            num_match = re.search(
                f"({constants.getattr('NUMBER_REGEX')}+)", item
            ) or re.search(f"^({constants.getattr('NUMBER_REGEX')}+)$", item)
            name_match = re.search(f"^{constants.getattr('USERNAME_REGEX')}+$", item)
            if num_match:
                model_id = num_match.group(1)
                user_name = profile.scrape_profile(model_id)["username"]
            elif name_match:
                user_name = name_match.group(0)
                model_id = profile.get_id(user_name)
            else:
                continue
            log.info(f"Getting Messages/Paid content for {user_name}")

            await operations.table_init_create(model_id=model_id, username=user_name)
            # messages
            messages = None
            oldmessages = cache.get(f"message_check_{model_id}", default=[])
            log.debug(f"Number of messages in cache {len(oldmessages)}")

            if len(oldmessages) > 0 and not read_args.retriveArgs().force:
                messages = oldmessages
            else:
                messages = await messages_.get_messages(
                    model_id, user_name, forced_after=0,c=c
                )
                cache.set(
                    f"message_check_{model_id}",
                    messages,
                    expire=constants.getattr("DAY_SECONDS"),
                )
            message_posts_array = list(
                map(lambda x: posts_.Post(x, model_id, user_name), messages)
            )
            await operations.make_messages_table_changes(
                message_posts_array, model_id=model_id, username=user_name
            )

            oldpaid = cache.get(f"purchased_check_{model_id}", default=[])
            paid = None
            # paid content
            if len(oldpaid) > 0 and not read_args.retriveArgs().force:
                paid = oldpaid
            else:
                paid = await paid_.get_paid_posts(model_id, user_name, c=c)
                cache.set(
                    f"purchased_check_{model_id}",
                    paid,
                    expire=constants.getattr("DAY_SECONDS"),
                )
            paid_posts_array = list(
                map(lambda x: posts_.Post(x, model_id, user_name), paid)
            )
            await operations.make_changes_to_content_tables(
                paid_posts_array, model_id=model_id, username=user_name
            )

            media = await process_post_media(
                user_name,model_id, paid_posts_array + message_posts_array
            )

            downloaded = await get_downloaded(user_name, model_id, True)

            ROWS.extend(row_gather(media, downloaded, user_name))
    return ROWS


def purchase_checker():
    ROWS = purchase_checker_helper()
    start_helper(ROWS)


@run
async def purchase_checker_helper():
    user_dict = {}
    auth_requests.make_headers()
    ROWS = []
    async with sessionbuilder.sessionBuilder(backend="httpx") as c:
        for user_name in read_args.retriveArgs().usernames:
            user_name = profile.scrape_profile(user_name)["username"]
            user_dict[user_name] = user_dict.get(user_name, [])
            model_id = profile.get_id(user_name)

            await operations.table_init_create(model_id=model_id, username=user_name)

            oldpaid = cache.get(f"purchased_check_{model_id}", default=[])
            paid = None


            if len(oldpaid) > 0 and not read_args.retriveArgs().force:
                paid = oldpaid
            else:
                paid = await paid_.get_paid_posts(model_id, user_name, c=c)
                cache.set(
                    f"purchased_check_{model_id}",
                    paid,
                    expire=constants.getattr("DAY_SECONDS"),
                )
            posts_array = list(map(lambda x: posts_.Post(x, model_id, user_name), paid))
            await operations.make_changes_to_content_tables(
                posts_array, model_id=model_id, username=user_name
            )
            downloaded = await get_downloaded(user_name, model_id)
            media = await process_post_media(user_name, model_id,posts_array)
            ROWS.extend(row_gather(media, downloaded, user_name))
    return ROWS


def stories_checker():
    ROWS = stories_checker_helper()
    start_helper(ROWS)


@run
async def stories_checker_helper():
    user_dict = {}
    ROWS = []
    async with sessionbuilder.sessionBuilder(backend="httpx") as c:
        for user_name in read_args.retriveArgs().usernames:
            user_name = profile.scrape_profile(user_name)["username"]
            user_dict[user_name] = user_dict.get(user_name, [])
            model_id = profile.get_id(user_name)
            await operations.table_init_create(model_id=model_id, username=user_name)
            stories = await highlights.get_stories_post(model_id, c=c)
            highlights_ = await highlights.get_highlight_post(model_id, c=c)
            highlights_ = list(
                map(
                    lambda x: posts_.Post(x, model_id, user_name, "highlights"),
                    highlights_,
                )
            )
            stories = list(
                map(lambda x: posts_.Post(x, model_id, user_name, "stories"), stories)
            )

            downloaded = await get_downloaded(user_name, model_id)
            media = await process_post_media(user_name,model_id,stories+highlights_)
            ROWS.extend(row_gather(media, downloaded, user_name))
    return ROWS


def url_helper():
    out = []
    out.extend(read_args.retriveArgs().file or [])
    out.extend(read_args.retriveArgs().url or [])
    return map(lambda x: x.strip(), out)


@run
async def process_post_media(username,model_id,posts_array):
    seen = set()
    unduped = [
    post
        for post in posts_array
    if (post.id,post.username) not in seen and not seen.add((post.id,post.username))
    ]
    temp = []
    [temp.extend(ele.all_media) for ele in unduped]
    await operations.batch_mediainsert(
                temp,
                model_id=model_id,
                username=username,
                downloaded=False,
    )
    return temp


@run
async def get_downloaded(user_name, model_id, paid=False):
    downloaded = {}

    await operations.table_init_create(model_id=model_id, username=user_name)
    paid = await get_paid_ids(model_id, user_name) if paid else []
    [
        downloaded.update({ele: downloaded.get(ele, 0) + 1})
        for ele in operations.get_media_ids_downloaded(
            model_id=model_id, username=user_name
        )
        + paid
    ]

    return downloaded


@run
async def get_paid_ids(model_id, user_name):
    oldpaid = cache.get(f"purchased_check_{model_id}", default=[])
    paid = None

    if len(oldpaid) > 0 and not read_args.retriveArgs().force:
        paid = oldpaid
    else:
        async with sessionbuilder.sessionBuilder(backend="httpx") as c:
            paid = await paid_.get_paid_posts(model_id, user_name, c=c)
            cache.set(
                f"purchased_check_{model_id}",
                paid,
                expire=constants.getattr("DAY_SECONDS"),
            )
    media = await process_post_media(user_name,model_id, paid)
    media = list(filter(lambda x: x.canview == True, media))
    return list(map(lambda x: x.id, media))


def thread_starters(ROWS_):
    worker_thread = threading.Thread(target=process_download_cart, daemon=True)
    worker_thread.start()
    process_download_cart.counter = 0
    start_table(ROWS_)


def start_table(ROWS_):
    global app
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = table.InputApp()
    app.mutex = threading.Lock()
    app.row_queue = queue.Queue()
    ROWS = get_first_row()
    ROWS.extend(ROWS_)

    app.table_data = ROWS
    app.row_names = ROW_NAMES
    app._filtered_rows = app.table_data[1:]
    app.run()


def get_first_row():
    return [ROW_NAMES]


def texthelper(text):
    text = text or ""
    text = inspect.cleandoc(text)
    text = re.sub(" +$", "", text)
    text = re.sub("^ +", "", text)
    text = re.sub("<[^>]*>", "", text)
    text = (
        text
        if len(text) < constants.getattr("TABLE_STR_MAX")
        else f"{text[:constants.getattr('TABLE_STR_MAX')]}..."
    )
    return text


def unlocked_helper(ele):
    return ele.canview


def datehelper(date):
    if date == "None":
        return "Probably Deleted"
    return date


def times_helper(ele, mediadict, downloaded):
    return max(len(mediadict.get(ele.id, [])), downloaded.get(ele.id, 0))


def checkmarkhelper(ele):
    return "[]" if unlocked_helper(ele) else "Not Unlocked"


def row_gather(media, downloaded, username):
    # fix text

    mediadict = {}
    [
        mediadict.update({ele.id: mediadict.get(ele.id, []) + [ele]})
        for ele in list(filter(lambda x: x.canview, media))
    ]
    out = []
    media = sorted(media, key=lambda x: arrow.get(x.date), reverse=True)
    for count, ele in enumerate(media):
        out.append(
            [
                None,
                checkmarkhelper(ele),
                username,
                ele.id in downloaded
                or cache.get(ele.postid) != None
                or cache.get(ele.filename) != None,
                unlocked_helper(ele),
                times_helper(ele, mediadict, downloaded),
                ele.numeric_length,
                ele.mediatype,
                datehelper(ele.formatted_postdate),
                len(ele._post.post_media),
                ele.responsetype,
                "Free" if ele._post.price == 0 else "{:.2f}".format(ele._post.price),
                ele.postid,
                ele.id,
                texthelper(ele.text),
            ]
        )
    return out
