r"""
                                                             
        _____                                               
  _____/ ____\______ ________________    ____   ___________ 
 /  _ \   __\/  ___// ___\_  __ \__  \  /  _ \_/ __ \_  __ \
(  <_> )  |  \___ \\  \___|  | \// __ \(  <_> )  ___/|  | \/
 \____/|__| /____  >\___  >__|  (____  /\____/ \___  >__|   
                 \/     \/           \/            \/         
"""

import asyncio
import math
import pathlib
import platform
import sys
import shutil
import traceback
import re
import httpx
import os
import contextvars
import json
import subprocess

from rich.console import Console
console=Console()
from tqdm.asyncio import tqdm
import arrow
from bs4 import BeautifulSoup
try:
    from win32_setctime import setctime  # pylint: disable=import-error
except ModuleNotFoundError:
    pass
from tenacity import retry,stop_after_attempt,wait_random,retry_if_result
import ffmpeg
from .auth import add_cookies
from src.utils.logger import updateSenstiveDict
from .config import read_config
from .separate import separate_by_id
from ..db import operations
from .paths import set_directory,getmediadir,getcachepath,trunicate
from ..utils import auth
from ..constants import NUM_TRIES,FILE_FORMAT_DEFAULT,DATE_DEFAULT,TEXTLENGTH_DEFAULT,FILE_SIZE_DEFAULT
from ..utils.profiles import get_current_profile
from .dates import convert_local_time

from diskcache import Cache
cache = Cache(getcachepath())
attempt = contextvars.ContextVar("attempt")

config = read_config()['config']
import src.utils.logger as logger
log=logger.getlogger()

async def process_dicts(username, model_id, medialist,forced=False):
    if medialist:
    
        if not forced:
            media_ids = set(operations.get_media_ids(model_id,username))
            medialist = separate_by_id(medialist, media_ids)
            console.print(f"Skipping previously downloaded\nMedia left for download {len(medialist)}")
        else:
            print("forcing all downloads")
        file_size_limit = config.get('file_size_limit') or FILE_SIZE_DEFAULT
        global sem
        sem = asyncio.Semaphore(8)
      
        aws=[]
        photo_count = 0
        video_count = 0
        audio_count=0
        skipped = 0
        total_bytes_downloaded = 0
        data = 0
        desc = 'Progress: ({p_count} photos, {v_count} videos, {a_count} audios,  {skipped} skipped || {sumcount}/{mediacount}||{data})'    

        with tqdm(desc=desc.format(p_count=photo_count, v_count=video_count,a_count=audio_count, skipped=skipped,mediacount=len(medialist), sumcount=video_count+audio_count+photo_count+skipped,data=data), total=len(aws), colour='cyan', leave=True) as main_bar:   
            for ele in medialist:
                with set_directory(getmediadir(ele,username,model_id)):

                    aws.append(asyncio.create_task(download(ele,pathlib.Path(".").absolute() ,model_id, username,file_size_limit
                                                            )))
            for coro in asyncio.as_completed(aws):
                    try:
                        media_type, num_bytes_downloaded = await coro
                    except Exception as e:
                        media_type = "skipped"
                        num_bytes_downloaded = 0

                    total_bytes_downloaded += num_bytes_downloaded
                    data = convert_num_bytes(total_bytes_downloaded)
                    if media_type == 'images':
                        photo_count += 1
                        main_bar.set_description(
                            desc.format(
                                p_count=photo_count, v_count=video_count, a_count=audio_count,skipped=skipped, data=data,mediacount=len(medialist), sumcount=video_count+audio_count+photo_count+skipped), refresh=True)

                    elif media_type == 'videos':
                        video_count += 1
                        main_bar.set_description(
                            desc.format(
                                p_count=photo_count, v_count=video_count, a_count=audio_count ,skipped=skipped, data=data,mediacount=len(medialist), sumcount=video_count+audio_count+photo_count+skipped), refresh=True)

                    elif media_type == 'audios':
                        audio_count += 1
                        main_bar.set_description(
                            desc.format(
                                p_count=photo_count, v_count=video_count,a_count=audio_count , skipped=skipped, data=data,mediacount=len(medialist), sumcount=video_count+audio_count+photo_count+skipped), refresh=True)

                    elif media_type == 'skipped':
                        skipped += 1
                        main_bar.set_description(
                            desc.format(
                                p_count=photo_count, v_count=video_count,a_count=audio_count , skipped=skipped, data=data,mediacount=len(medialist), sumcount=video_count+audio_count+photo_count+skipped), refresh=True)

                    main_bar.update()
        log.warning(f'[bold]{username}[/bold] ({photo_count} photos, {video_count} videos, {audio_count} audios,  {skipped} skipped)' )
def retry_required(value):
    return value == ('skipped', 1)

@retry(retry=retry_if_result(retry_required),stop=stop_after_attempt(NUM_TRIES),wait=wait_random(min=20, max=40),reraise=True) 
async def download(ele,path,model_id,username,file_size_limit):
    attempt.set(attempt.get(0) + 1)
    
    try:
        if ele.url:
           return await main_download_helper(ele,path,file_size_limit,username,model_id)
        elif ele.mpd:        
            return await alt_download_helper(ele,path,file_size_limit,username,model_id)
        else:
            return "skipped",1
    except Exception as e:
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] exception {e}")   
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] exception {traceback.format_exc()}")   
        return 'skipped', 1
async def main_download_helper(ele,path,file_size_limit,username,model_id):
    url=ele.url
    log.debug(f"ID:{ele.id} Attempting to download media {ele.filename} with {url or 'no url'}")
    path_to_file=None
    async with sem:
            async with httpx.AsyncClient(http2=True, headers = auth.make_headers(auth.read_auth()), follow_redirects=True, timeout=None) as c: 
                auth.add_cookies(c)        
                async with c.stream('GET',url) as r:
                    if not r.is_error:
                        rheaders=r.headers
                        total = int(rheaders['Content-Length'])
                        if file_size_limit and total > int(file_size_limit): 
                                return 'skipped', 1       
                        content_type = rheaders.get("content-type").split('/')[-1]
                        filename=createfilename(ele,username,model_id,content_type)
                        path_to_file = trunicate(pathlib.Path(path,f"{filename}"))                 
                        pathstr=str(path_to_file)
                        temp=trunicate(f"{path_to_file}.part")
                        pathlib.Path(temp).unlink(missing_ok=True)
                        with tqdm(desc=f"{attempt.get()}/{NUM_TRIES} {(pathstr[:50] + '....') if len(pathstr) > 50 else pathstr}" ,total=total, unit_scale=True, unit_divisor=1024, unit='B', leave=False) as bar:
                            with open(temp, 'wb') as f:                           
                                num_bytes_downloaded = r.num_bytes_downloaded
                                async for chunk in r.aiter_bytes(chunk_size=1024):
                                    f.write(chunk)
                                    bar.update(r.num_bytes_downloaded - num_bytes_downloaded)
                                    num_bytes_downloaded = r.num_bytes_downloaded 
            
                    else:
                        r.raise_for_status()
    if not pathlib.Path(temp).exists():
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] {temp} was not created") 
        return "skipped",1
    elif abs(total-pathlib.Path(temp).absolute().stat().st_size)>500:
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] {ele.filename} size mixmatch target: {total} vs actual: {pathlib.Path(temp).absolute().stat().st_size}")   
        return "skipped",1 
    else:
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] {ele.filename} size match target: {total} vs actual: {pathlib.Path(temp).absolute().stat().st_size}")   
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] renaming {pathlib.Path(temp).absolute()} -> {path_to_file}")   
        shutil.move(temp,path_to_file)
        if ele.postdate:
            set_time(path_to_file, convert_local_time(ele.postdate))
        if ele.id:
            operations.write_media_table(ele,path_to_file,model_id,username)
        return ele.mediatype,total

async def alt_download_helper(ele,path,file_size_limit,username,model_id):
    video = None
    audio = None
    base_url=re.sub("[0-9a-z]*\.mpd$","",ele.mpd,re.IGNORECASE)
    mpd=ele.parse_mpd
    path_to_file = trunicate(pathlib.Path(path,f'{createfilename(ele,username,model_id,"mp4")}')) 

    for period in mpd.periods:
        for adapt_set in filter(lambda x:x.mime_type=="video/mp4",period.adaptation_sets):             
            kId=None
            for prot in adapt_set.content_protections:
                if prot.value==None:
                    kId = prot.pssh[0].pssh 
                    break
            maxquality=max(map(lambda x:x.height,adapt_set.representations))
            for repr in adapt_set.representations:
                if repr.height==maxquality:
                    video={"name":repr.base_urls[0].base_url_value,"pssh":kId,"type":"video"}
                    break
        for adapt_set in filter(lambda x:x.mime_type=="audio/mp4",period.adaptation_sets):             
            kId=None
            for prot in adapt_set.content_protections:
                if prot.value==None:
                    kId = prot.pssh[0].pssh 
                    updateSenstiveDict(kId,"pssh_code")
                    break
            maxquality=max(map(lambda x:x.height,adapt_set.representations))
            for repr in adapt_set.representations:
                audio={"name":repr.base_urls[0].base_url_value,"pssh":kId,"type":"audio"}
                break
        for item in [audio,video]:
            url=f"{base_url}{item['name']}"
            log.debug(f"ID:{ele.id} Attempting to download media {item['name']} with {url or 'no url'}")
            async with sem:
                params={"Policy":ele.policy,"Key-Pair-Id":ele.keypair,"Signature":ele.signature}   
                async with httpx.AsyncClient(http2=True, headers = auth.make_headers(auth.read_auth()), follow_redirects=True, timeout=None,params=params) as c: 
                    auth.add_cookies(c) 
                    async with c.stream('GET',url) as r:
                        if not r.is_error:
                            rheaders=r.headers
                            total = int(rheaders['Content-Length'])
                            item["total"]=total
                            if file_size_limit and total > int(file_size_limit): 
                                    return 'skipped', 1       
                            temp= trunicate(pathlib.Path(path,f"{item['name']}.part"))
                            temp.unlink(missing_ok=True)
                            item["path"]=temp
                            pathstr=str(temp)
                            with tqdm(desc=f"{attempt.get()}/{NUM_TRIES} {(pathstr[:50] + '....') if len(pathstr) > 50 else pathstr}" ,total=total, unit_scale=True, unit_divisor=1024, unit='B', leave=False) as bar:
                                with open(temp, 'wb') as f:                           
                                    num_bytes_downloaded = r.num_bytes_downloaded
                                    async for chunk in r.aiter_bytes(chunk_size=1024):
                                        f.write(chunk)
                                        bar.update(r.num_bytes_downloaded - num_bytes_downloaded)
                                        num_bytes_downloaded = r.num_bytes_downloaded      
                        else:
                            r.raise_for_status()
    log.debug(f"ID:{ele.id} video name:{video['name']}")
    log.debug(f"ID:{ele.id} audio name:{audio['name']}")
    for item in [audio,video]:
        if not pathlib.Path(item["path"]).exists():
                log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] {item['path']} was not created") 
                return "skipped",1
        elif abs(item["total"]-pathlib.Path(item['path']).absolute().stat().st_size)>500:
            log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] {item['name']} size mixmatch target: {total} vs actual: {pathlib.Path(item['path']).absolute().stat().st_size}")   
            return "skipped",1 
                
    for item in [audio,video]:
        key=await key_helper(item["pssh"],ele.license,ele.id)
        if key==None:
            return "skipped",1 
        newpath=pathlib.Path(re.sub("\.part$","",str(item["path"]),re.IGNORECASE))
        log.debug(f"ID:{ele.id} [attempt {attempt.get()}/{NUM_TRIES}] renaming {pathlib.Path(item['path']).absolute()} -> {newpath}")   
        subprocess.run([read_config()["config"].get('mp4decrypt'),"--key",key,str(item["path"]),str(newpath)])
        pathlib.Path(item["path"]).unlink(missing_ok=True)
        item["path"]=newpath
    path_to_file.unlink(missing_ok=True)
   
    ffmpeg.output( ffmpeg.input(str(video["path"])), ffmpeg.input(str(audio["path"])), str(path_to_file),codec='copy',loglevel="quiet").overwrite_output().run( capture_stdout=True)
    video["path"].unlink(missing_ok=True)
    audio["path"].unlink(missing_ok=True)

async def key_helper(pssh,licence_url,id):
    out=None
    log.debug(f"ID:{id} pssh: {pssh!=None}")
    log.debug(f"ID:{id} licence: {licence_url}")
    if not out:
        headers=auth.make_headers(auth.read_auth())
        headers["cookie"]=auth.get_cookies()
        auth.create_sign(licence_url,headers)
        json_data = {
            'license': str(httpx.URL(licence_url)),
            'headers': json.dumps(headers),
            'pssh': pssh,
            'buildInfo': '',
            'proxy': '',
            'cache': True,
        }


        
        async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=None) as c: 
            r=await c.post('https://cdrm-project.com/wv',json=json_data)
            log.debug(f"ID:{id} key_response: {r.content.decode()}")
            soup = BeautifulSoup(r.content, 'html.parser')
            out=soup.find("li").contents[0]
            cache.set(licence_url,out, expire=2592000)
            cache.close()
    return out
        


  
def convert_num_bytes(num_bytes: int) -> str:
    if num_bytes == 0:
      return '0 B'
    num_digits = int(math.log10(num_bytes)) + 1

    if num_digits >= 10:
        return f'{round(num_bytes / 10**9, 2)} GB'
    return f'{round(num_bytes / 10 ** 6, 2)} MB'

               
def set_time(path, timestamp):
    if platform.system() == 'Windows':
        setctime(path, timestamp)
    pathlib.os.utime(path, (timestamp, timestamp))


def get_error_message(content):
    error_content = content.get('error', 'No error message available')
    try:
        return error_content.get('message', 'No error message available')
    except AttributeError:
        return error_content
def createfilename(ele,username,model_id,ext):
    if ele.responsetype =="profile":
        return "{filename}.{ext}".format(ext=ext,filename=ele.filename)
    return (config.get('file_format') or FILE_FORMAT_DEFAULT).format(filename=ele.filename,sitename="Onlyfans",site_name="Onlyfans",post_id=ele.id_,media_id=ele.id,first_letter=username[0],mediatype=ele.mediatype,value=ele.value,text=ele.text_,date=arrow.get(ele.postdate).format(config.get('date') or DATE_DEFAULT),ext=ext,model_username=username,model_id=model_id,responsetype=ele.responsetype) 





