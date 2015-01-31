#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 4chan Archiver Class
from __future__ import print_function
from __future__ import absolute_import

from .base import BaseSiteArchiver, DownloadItem
from .. import utils

import basc_py4chan

import os
import re
import time
import codecs
import threading

# finding board name/thread id
THREAD_REGEX = re.compile(r"""https?://(?:boards\.)?4chan\.org/([0-9a-zA-Z]+)/(?:res|thread)/([0-9]+)""")

# top level domains
FOURCHAN_BOARDS = 'boards.4chan.org'
FOURCHAN_CDN = '4cdn.org'

# cdn domains
FOURCHAN_API = 'a.' + FOURCHAN_CDN
FOURCHAN_IMAGES = 'i.' + FOURCHAN_CDN
FOURCHAN_THUMBS = 't.' + FOURCHAN_CDN
FOURCHAN_STATIC = 's.' + FOURCHAN_CDN

# retrieval footer regex
FOURCHAN_BOARDS_FOOTER = '/%s/thread/%s'
FOURCHAN_API_FOOTER = FOURCHAN_BOARDS_FOOTER + '.json'
FOURCHAN_IMAGES_FOOTER = '/%s/%s'
FOURCHAN_THUMBS_FOOTER = '/%s/%s'

# download urls
FOURCHAN_BOARDS_URL = FOURCHAN_BOARDS + FOURCHAN_BOARDS_FOOTER
FOURCHAN_API_URL = FOURCHAN_API + FOURCHAN_API_FOOTER
FOURCHAN_IMAGES_URL = FOURCHAN_IMAGES + FOURCHAN_IMAGES_FOOTER
FOURCHAN_THUMBS_URL = FOURCHAN_THUMBS + FOURCHAN_THUMBS_FOOTER

# html parsing regex
HTTP_HEADER_UNIV = r"https?://"  # works for both http and https links
FOURCHAN_IMAGES_REGEX = r"/\w+/"
FOURCHAN_THUMBS_REGEX = r"/\w+/"
FOURCHAN_CSS_REGEX = r"/css/(\w+\.\d+.css)"
FOURCHAN_JS_REGEX = r"/js/(\w+\.\d+.js)"
CHILDREGEX = re.compile(r"""href="/([0-9a-zA-Z]+)/(?:res|thread)/([0-9]+)""")

# regex links to 4chan servers
FOURCHAN_IMAGES_URL_REGEX = re.compile(HTTP_HEADER_UNIV + FOURCHAN_IMAGES + FOURCHAN_IMAGES_REGEX)
FOURCHAN_THUMBS_URL_REGEX = re.compile(HTTP_HEADER_UNIV + "(?:\d+.)?" + FOURCHAN_THUMBS + FOURCHAN_THUMBS_REGEX)
FOURCHAN_CSS_URL_REGEX = re.compile(HTTP_HEADER_UNIV + FOURCHAN_STATIC + '/css/')
FOURCHAN_JS_URL_REGEX = re.compile(HTTP_HEADER_UNIV + FOURCHAN_STATIC + '/js/')

# default folder and file names
_DEFAULT_FOLDER = '4chan'
_IMAGE_DIR_NAME = 'images'
_THUMB_DIR_NAME = 'thumbs'
_CSS_DIR_NAME = 'css'
_JS_DIR_NAME = 'js'
EXT_LINKS_FILENAME = 'external_links.txt'

# The Ultimate URL Regex
# http://stackoverflow.com/questions/520031/whats-the-cleanest-way-to-extract-urls-from-a-string-using-python
URLREGEX = re.compile(r"""((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]|[a-z0-9.\-]+[.‌​][a-z]{2,4}/)(?:[^\s()<>]+|(([^\s()<>]+|(([^\s()<>]+)))*))+(?:(([^\s()<>]+|(‌​([^\s()<>]+)))*)|[^\s`!()[]{};:'".,<>?«»“”‘’]))""", re.DOTALL)


class FourChanSiteArchiver(BaseSiteArchiver):
    name = '4chan'
    def __init__(self, callback_handler, options):
        BaseSiteArchiver.__init__(self, callback_handler, options)

        self.boards_lock = threading.Lock()
        self.boards = {}

    def url_valid(self, url):
        """Return true if the given URL is for my site."""
        return THREAD_REGEX.match(url)

    def _url_info(self, url):
        """INTERNAL: Takes a url, returns board name, thread info."""
        if self.url_valid(url):
            return THREAD_REGEX.findall(url)[0]
        else:
            return [None, None]

    def add_thread(self, url, only_download_once=False, download_delay_in_seconds=90):
        """Add the given thread to our download list."""
        board_name, thread_id = self._url_info(url)
        thread_id = int(thread_id)
        return self._add_thread_from_info(board_name, thread_id,
                                          only_download_once=only_download_once,
                                          download_delay_in_seconds=download_delay_in_seconds)

    def _add_thread_from_info(self, board_name, thread_id, only_download_once=False, download_delay_in_seconds=90):
        """Add a thread to our internal list from direct board name/thread id."""
        # already exists
        with self.threads_lock:
            if thread_id in self.threads:
                return True

        # running board object
        with self.boards_lock:
            if board_name not in self.boards:
                self.boards[board_name] = basc_py4chan.Board(board_name, https=self.options.use_ssl)
            running_board = self.boards[board_name]

            if not running_board.thread_exists(thread_id):
                print('4chan Thread {} / {} does not exist.'.format(board_name, thread_id))
                print("Either the thread already 404'ed, your URL is incorrect, or you aren't connected to the internet.")
                return False

        # add thread to download list
        with self.threads_lock:
            self.threads[thread_id] = {
                'board': board_name,
                'dir': self.base_thread_dir.format(board=board_name, thread=thread_id),
                'thread_id': thread_id,
                'total_files': 0,
                'images_downloaded': 0,
                'thumbs_downloaded': 0,
            }
            status_info = self.threads[thread_id]
        self.update_status('new_thread', info=status_info)

        self.add_to_dl('thread', board=board_name, thread_id=thread_id,
                       only_download_once=only_download_once,
                       download_delay_in_seconds=download_delay_in_seconds)

    def download_item(self, item):
        """Download the given item."""
        http_header = ('https://' if self.options.use_ssl else 'http://')

        # images
        if item.dl_type == 'image':
            if self.options.thumbs_only:
                return True

            board_name = item.info['board']
            thread_id = item.info['thread_id']
            images_dir = self.base_images_dir.format(board=board_name, thread=thread_id)
            filename = item.info['filename']

            file_url = http_header + FOURCHAN_IMAGES_URL % (board_name, filename)
            file_path = os.path.join(images_dir, filename)

            if not os.path.exists(file_path):
                utils.mkdirs(images_dir)
                if utils.download_file(file_path, file_url):
                    with self.threads_lock:
                        self.threads[thread_id]['images_downloaded'] += 1
                        status_info = self.threads[thread_id]
                        status_info['filename'] = filename
                    self.update_status('image_dl', info=status_info)
                    if not self.options.silent:
                        print('  Image {} / {} / {} downloaded'.format(board_name, thread_id, filename))

        # thumbnails
        elif item.dl_type == 'thumb':
            if self.options.skip_thumbs:
                return True

            board_name = item.info['board']
            thread_id = item.info['thread_id']
            thumbs_dir = self.base_thumbs_dir.format(board=board_name, thread=thread_id)
            filename = item.info['filename']

            file_url = http_header + FOURCHAN_THUMBS_URL % (board_name, filename)
            file_path = os.path.join(thumbs_dir, filename)

            if not os.path.exists(file_path):
                utils.mkdirs(thumbs_dir)
                if utils.download_file(file_path, file_url):
                    with self.threads_lock:
                        self.threads[thread_id]['thumbs_downloaded'] += 1
                        status_info = self.threads[thread_id]
                        status_info['filename'] = filename
                    self.update_status('thumb_dl', info=status_info)
                    if not self.options.silent:
                        print('  Thumbnail {} / {} / {} downloaded'.format(board_name, thread_id, filename))

        # thread
        elif item.dl_type == 'thread':
            board_name = item.info['board']
            thread_id = item.info['thread_id']
            thread_dir = self.base_thread_dir.format(board=board_name, thread=thread_id)

            with self.threads_lock:
                status_info = self.threads[thread_id]
            self.update_status('thread_start_download', info=status_info)

            thread = self.threads[thread_id]
            with self.boards_lock:
                # skip if no new posts
                if 'thread' in thread:
                    new_replies = thread['thread'].update()
                    if new_replies < 1:
                        # skip if no new posts
                        item.delay_dl_timestamp()

                        with self.threads_lock:
                            status_info = self.threads[thread_id]
                        status_info['next_dl'] = item.next_dl_timestamp
                        self.update_status('thread_dl', info=status_info)

                        self.add_to_dl(item=item)
                        return True
                    elif thread['thread'].is_404:
                        # thread 404'd
                        print("Thread {} / {} 404'd.".format(board_name, thread_id))
                        with self.threads_lock:
                            status_info = self.threads[thread_id]
                        self.update_status('404', info=status_info)
                        del self.threads[thread_id]
                        return True
                    else:
                        with self.threads_lock:
                            # TODO: extend BASC-py4chan to give us this number directly
                            self.threads[thread_id]['total_files'] = len(list(running_thread.filenames()))
                else:
                    running_board = self.boards[board_name]
                    running_thread = running_board.get_thread(thread_id)
                    self.threads[thread_id]['thread'] = running_thread
                    thread['thread'] = running_thread
                    new_replies = len(running_thread.all_posts)
                    with self.threads_lock:
                        # TODO: extend BASC-py4chan to give us this number directly
                        self.threads[thread_id]['total_files'] = len(list(running_thread.filenames()))

            # thread
            if not self.options.silent:
                print('4chan Thread {} / {}  -  {} new replies'.format(board_name, thread_id, new_replies))

            utils.mkdirs(thread_dir)

            # record external urls and follow child threads
            external_urls_filename = os.path.join(thread_dir, EXT_LINKS_FILENAME)
            with codecs.open(external_urls_filename, 'w', encoding='utf-8') as external_urls_file:
                # all posts, including topic
                all_posts = [thread['thread'].topic]
                for reply in all_posts:
                    if reply.comment is None:
                        continue

                    # 4chan puts <wbr> in middle of urls for word break, remove them
                    cleaned_comment = re.sub(r'\<wbr\>', '', reply.comment)

                    # child threads
                    if self.options.follow_child_threads:
                        for child_board, child_id in CHILDREGEX.findall(cleaned_comment):
                            is_same_board = child_board == board_name
                            child_id = int(child_id)

                            if child_id not in self.threads:
                                if self.options.follow_to_other_boards or not self.options.follow_to_other_boards and is_same_board:
                                    print('4chan child thread {} / {} found and now being downloaded'.format(child_board, child_id))
                                    self._add_thread_from_info(child_board, child_id)

                    # external urls
                    if not URLREGEX.findall(reply.comment):
                        continue

                    for found in URLREGEX.findall(cleaned_comment):
                        for url in found:
                            if url:
                                external_urls_file.write('{}\n'.format(url))

            # dump 4chan json file, pretty printed
            local_filename = os.path.join(thread_dir, '{}.json'.format(thread_id))
            url = http_header + FOURCHAN_API_URL % (board_name, thread_id)
            utils.download_json(local_filename, url, clobber=True)

            # and output thread html file
            local_filename = os.path.join(thread_dir, '{}.html'.format(thread_id))
            url = http_header + FOURCHAN_BOARDS_URL % (board_name, thread_id)

            if utils.download_file(local_filename, url, clobber=True):
                # get css files
                css_dir = os.path.join(thread_dir, _CSS_DIR_NAME)
                utils.mkdirs(css_dir)

                css_regex = re.compile(FOURCHAN_CSS_REGEX)
                found_css_files = css_regex.findall(codecs.open(local_filename, encoding='utf-8').read())
                for css_filename in found_css_files:
                    local_css_filename = os.path.join(css_dir, css_filename)
                    url = http_header + FOURCHAN_STATIC + '/css/' + css_filename
                    utils.download_file(local_css_filename, url)

                # get js files
                js_dir = os.path.join(thread_dir, _JS_DIR_NAME)
                utils.mkdirs(js_dir)

                js_regex = re.compile(FOURCHAN_JS_REGEX)
                found_js_files = js_regex.findall(codecs.open(local_filename, encoding='utf-8').read())
                for js_filename in found_js_files:
                    local_js_filename = os.path.join(js_dir, js_filename)
                    url = http_header + FOURCHAN_STATIC + '/js/' + js_filename
                    utils.download_file(local_js_filename, url)

                # convert links to local links
                utils.file_replace(local_filename, '"//', '"' + http_header)
                utils.file_replace(local_filename, FOURCHAN_IMAGES_URL_REGEX, _IMAGE_DIR_NAME + '/')
                utils.file_replace(local_filename, FOURCHAN_THUMBS_URL_REGEX, _THUMB_DIR_NAME + '/')
                utils.file_replace(local_filename, FOURCHAN_CSS_URL_REGEX, _CSS_DIR_NAME + '/')
                utils.file_replace(local_filename, FOURCHAN_JS_URL_REGEX, _JS_DIR_NAME + '/')

            # add images to dl queue
            for filename in thread['thread'].filenames():
                self.add_to_dl(dl_type='image', board=board_name, thread_id=thread_id, filename=filename)

            # add thumbs to dl queue
            for filename in thread['thread'].thumbnames():
                self.add_to_dl(dl_type='thumb', board=board_name, thread_id=thread_id, filename=filename)

            # queue for next dl
            if not item.info['only_download_once']:
                item.delay_dl_timestamp(self.options.thread_check_delay)
                self.add_to_dl(item=item)

            with self.threads_lock:
                status_info = self.threads[thread_id]
            if item.info['only_download_once']:
                status_info['stopped'] = True
            else:
                status_info['stopped'] = False
                status_info['next_dl'] = item.next_dl_timestamp
            self.update_status('thread_dl', info=status_info)
