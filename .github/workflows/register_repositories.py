import asyncio
import copy
import json
import logging
import os
import urllib
from datetime import datetime

import aiohttp
import ruamel.yaml as yaml

logging.basicConfig(level=logging.INFO)

API_BASE_URL = "https://api.github.com"

XDEVBOT_MAIN_ENDPOINT = "http://xdevbot.herokuapp.com/gh/testing"

def validate_repo_campaign_info(info, config):
    error_messages = []
    valid = True
    expected_keys = {'campaign', 'repo'}
    if set(info.keys()) == expected_keys:
        if info['campaign'] not in config:
            error_messages.append(
                f"  - Unknown campaign: `{info['campaign']}`. Valid campaigns include {', '.join(f'`{key}`' for key in config.keys())}."
            )
            valid = False

        if not info['repo']:
            valid = False
            error_messages.append('\n  - No specified repository')

    else:
        valid = False
        error_messages.append(
            f'  - Found unexpected keys {", ".join(f"`{key}`" for key in info.keys())} in the parsed command. Expected keys are {", ".join(f"`{key}``" for key in expected_keys)}.'
        )

    return valid, error_messages


def parse_line(line, original_config, repos={'remove': [], 'add': []}):
    config = copy.deepcopy(original_config)
    error_messages = []
    add_cmd = '/add-repo'
    remove_cmd = '/remove-repo'
    valid_line = add_cmd in line or remove_cmd in line
    if valid_line:
        split_on = add_cmd if add_cmd in line else remove_cmd
        parsed_info = line.split(split_on)[-1].strip().split()[:2]
        info = {}
        for item in parsed_info:
            x = item.strip().split(':')
            info[x[0]] = x[1]

        valid, error_messages = validate_repo_campaign_info(info, config)

        if valid:
            if split_on == add_cmd:
                if config[info['campaign']]['repos'] is None:
                    config[info['campaign']]['repos'] = []
                if info['repo'] not in set(config[info['campaign']]['repos']):
                    config[info['campaign']]['repos'].append(info['repo'])
                    repos['add'].append(info['repo'])

            else:
                try:
                    if config[info['campaign']]['repos'] is not None:
                        config[info['campaign']]['repos'].remove(info['repo'])
                except ValueError:
                    error_messages.append(
                        f"  - Unable to remove the repo `{info['repo']}` because it doesn't exist in the list of repos {', '.join(f'`{r}`' for r in config[info['campaign']]['repos'])} of the `{info['campaign']}` campaign."
                    )
                finally:
                    repos['remove'].append(info['repo'])

    if error_messages:
        error_messages = f"{line}\n{' '.join(error_messages)}\n"
    else:
        error_messages = ''
    return config, error_messages


def configure(original_config):
    error_messages_to_report = []
    repos = {'remove': [], 'add': []}
    with open(os.environ['GITHUB_EVENT_PATH'], 'r') as f:
        event_payload = json.load(f)
    comment = event_payload['issue']['body']
    # comment = """
    # Foo\n- /add-repo repo:NCAR/integral campaign:analysis\n- /add-repo repo:NCAR/test campaign:core\nbar\n- /remove-repo repo:NCAR/xdevbot-testing campaign:core\n/add-repo repo:NCAR/xdev-bot-testing campaign:core\n
    # \n- /remove-repo repo:NCAR/jupyterlab-pbs campaign:platform\n- /add-repo repo: campaign:test
    # """
    comment = comment.splitlines()

    config = copy.deepcopy(original_config)
    for line in comment:
        config, error_messages = parse_line(line, config, repos)
        if error_messages:
            error_messages_to_report.append(error_messages)

    return config, original_config, repos, error_messages_to_report


async def delete_repo_webhook(
    repo,
    hooks_info={},
    username=os.environ.get('GH_USERNAME', ''),
    token=os.environ.get('GH_TOKEN', ''),
):

    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {token}',
        'User-Agent': username,
    }

    url = f'{API_BASE_URL}/repos/{repo}/hooks'

    async with aiohttp.ClientSession(headers=headers) as client:

        logging.info('Retrieving repository webhooks metadata.')
        async with client.get(url) as response:
            hooks = await response.json()
            if response.status == 200:
                potl_hooks = []
                for hook in hooks:
                    if (
                        set(hook['events']) == {'issues', 'pull_request'}
                        and hook['config']['url'] == XDEVBOT_MAIN_ENDPOINT
                        and hook['config']['content_type'] == 'json'
                    ):
                        potl_hooks.append(hook)

                if potl_hooks:
                    for hook in potl_hooks:
                        logging.info('Deleting repository webhook.')
                        url = f"{url}/{hook['id']}"
                        async with client.delete(url) as response:
                            if response.status != 204:
                                logging.error('Failed to delete repository webhook.')
                            else:
                                logging.info('Deleted repository webhook.')
                                hooks_info[repo] = url


async def install_repo_webhook(
    repo,
    hooks_info={},
    username=os.environ.get('GH_USERNAME', ''),
    token=os.environ.get('GH_TOKEN', ''),
):

    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {token}',
        'User-Agent': username,
    }

    url = f'{API_BASE_URL}/repos/{repo}/hooks'

    async with aiohttp.ClientSession(headers=headers) as client:

        logging.info('Retrieving repository webhooks metadata.')
        async with client.get(url) as response:
            hooks = await response.json()
            if response.status == 200:
                potl_hooks = []
                for hook in hooks:
                    if (
                        set(hook['events']) == {'issues', 'pull_request'}
                        and hook['config']['url'] == XDEVBOT_MAIN_ENDPOINT
                        and hook['config']['content_type'] == 'json'
                        and hook['active']
                    ):
                        potl_hooks.append(hook)

                if len(potl_hooks) == 0:
                    logging.info('Creating repository webhook.')
                    request = dict(
                        name='web',
                        events=['issues', 'pull_request'],
                        config=dict(url=XDEVBOT_MAIN_ENDPOINT, content_type='json'),
                    )
                    async with client.post(url, json=request) as response:
                        main_hook = await response.json()
                        if response.status != 201:
                            logging.error('Failed to create repository webhook.')

                elif len(potl_hooks) == 1:
                    logging.info('Existing repository webhook found.')
                    main_hook = potl_hooks[0]

                else:
                    timestamps = [
                        datetime.strptime(hook['updated_at'], '%Y-%m-%dT%H:%M:%SZ')
                        for hook in potl_hooks
                    ]
                    newest_timestamp, i_hook = max((t, i) for (i, t) in enumerate(timestamps))[1]
                    logging.info(
                        f'Found {len(potl_hooks)} potential webhooks on the repository, '
                        f'choosing most recent webhook at {newest_timestamp}.'
                    )
                    main_hook = potl_hooks[i_hook]

                hooks_info[repo] = main_hook

            else:
                logging.error('Could not retrieve repository metadata.')


def format_repo_url(repo):
    return f'[{repo}](https://github.com/{repo})'


if __name__ == '__main__':

    remote_config_file = 'https://raw.githubusercontent.com/NCAR/xdev/xdevbot/xdevbot.yaml'
    config_file = 'xdevbot.yaml'
    resp = urllib.request.urlopen(remote_config_file)
    original_config = yaml.safe_load(resp)
    new_config, old_config, repos, error_messages_to_report = configure(original_config)
    if new_config != old_config:
        with open(config_file, 'w') as file_obj:
            yaml.round_trip_dump(new_config, file_obj, indent=2, block_seq_indent=2)

    added_hooks = {}
    removed_hooks = {}
    loop = asyncio.get_event_loop()
    add_tasks = [loop.create_task(install_repo_webhook(repo, added_hooks)) for repo in repos['add']]
    remove_tasks = [
        loop.create_task(delete_repo_webhook(repo, removed_hooks)) for repo in repos['remove']
    ]
    loop.run_until_complete(asyncio.gather(*add_tasks))
    loop.run_until_complete(asyncio.gather(*remove_tasks))

    added_successes = set(added_hooks.keys())
    added_failures = set(repos['add']) - added_successes
    removed_successes = set(removed_hooks.keys())
    removed_failures = set(repos['remove']) - removed_successes

    with open('hooks_log.md', 'w') as f:
        if error_messages_to_report:
            print('\n#### Errors comming from the provided commands', file=f)
            for error in error_messages_to_report:
                print(f'\n{error}', file=f)

        print('\n#### Additions', file=f)
        if added_successes:
            print(
                '\n**The webhook was successfully installed on the following repositories:**\n',
                file=f,
            )
            for repo in added_successes:
                print(f'- {format_repo_url(repo)}', file=f)

        if added_failures:
            print(
                '\n**Unable to install the webhook on the following repositories:**\n', file=f,
            )
            for repo in added_failures:
                print(f'- {format_repo_url(repo)}', file=f)

        print('\n#### Deletions', file=f)
        if removed_successes:
            print(
                '\n**The webhook was successfully removed on the following repositories:**\n',
                file=f,
            )
            for repo in removed_successes:
                print(f'- {format_repo_url(repo)}', file=f)

        if removed_failures:
            print(
                '\n**Unable to uninstall the webhook on the following repositories:**\n', file=f,
            )
            for repo in removed_failures:
                print(f'- {format_repo_url(repo)}', file=f)



