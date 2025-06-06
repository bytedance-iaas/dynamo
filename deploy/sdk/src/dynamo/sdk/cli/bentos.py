#  SPDX-FileCopyrightText: Copyright (c) 2020 Atalaya Tech. Inc
#  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
#  SPDX-License-Identifier: Apache-2.0
#  #
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  #
#  http://www.apache.org/licenses/LICENSE-2.0
#  #
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#  Modifications Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES

from __future__ import annotations

import json
import logging
import os
import subprocess
import typing as t

import attr
import click
import click_option_group as cog
import rich
import yaml
from bentoml._internal.bento.bento import DEFAULT_BENTO_BUILD_FILES
from bentoml._internal.bento.build_config import BentoBuildConfig
from bentoml._internal.configuration.containers import BentoMLContainer
from bentoml._internal.utils.args import set_arguments
from bentoml._internal.utils.filesystem import resolve_user_filepath
from bentoml.exceptions import InvalidArgument
from bentoml_cli.utils import is_valid_bento_name, is_valid_bento_tag
from rich.syntax import Syntax
from rich.table import Table
from simple_di import Provide, inject

from .bento_util import Bento

if t.TYPE_CHECKING:
    from bentoml._internal.bento import BentoStore
    from bentoml._internal.cloud import BentoCloudClient
    from bentoml._internal.container import DefaultBuilder
    from click import Context, Parameter

logger = logging.getLogger(__name__)

DYNAMO_FIGLET = """
██████╗ ██╗   ██╗███╗   ██╗ █████╗ ███╗   ███╗ ██████╗
██╔══██╗╚██╗ ██╔╝████╗  ██║██╔══██╗████╗ ████║██╔═══██╗
██║  ██║ ╚████╔╝ ██╔██╗ ██║███████║██╔████╔██║██║   ██║
██║  ██║  ╚██╔╝  ██║╚██╗██║██╔══██║██║╚██╔╝██║██║   ██║
██████╔╝   ██║   ██║ ╚████║██║  ██║██║ ╚═╝ ██║╚██████╔╝
╚═════╝    ╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚═╝ ╚═════╝
"""

ALLOWED_PLATFORMS = [
    "windows",
    "linux",
    "macos",
    "x86_64-pc-windows-msvc",
    "i686-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "aarch64-unknown-linux-gnu",
    "aarch64-unknown-linux-musl",
    "x86_64-unknown-linux-musl",
    "x86_64-manylinux_2_17",
    "x86_64-manylinux_2_28",
    "x86_64-manylinux_2_31",
    "x86_64-manylinux_2_32",
    "x86_64-manylinux_2_33",
    "x86_64-manylinux_2_34",
    "x86_64-manylinux_2_35",
    "x86_64-manylinux_2_36",
    "x86_64-manylinux_2_37",
    "x86_64-manylinux_2_38",
    "x86_64-manylinux_2_39",
    "x86_64-manylinux_2_40",
    "aarch64-manylinux_2_17",
    "aarch64-manylinux_2_28",
    "aarch64-manylinux_2_31",
    "aarch64-manylinux_2_32",
    "aarch64-manylinux_2_33",
    "aarch64-manylinux_2_34",
    "aarch64-manylinux_2_35",
    "aarch64-manylinux_2_36",
    "aarch64-manylinux_2_37",
    "aarch64-manylinux_2_38",
    "aarch64-manylinux_2_39",
    "aarch64-manylinux_2_40",
]


def parse_delete_targets_argument_callback(
    ctx: Context,
    params: Parameter,
    value: t.Any,  # pylint: disable=unused-argument
) -> list[str]:
    if value is None:
        return []
    value = " ".join(value)
    if "," in value:
        delete_targets = value.split(",")
    else:
        delete_targets = value.split()
    delete_targets = list(map(str.strip, delete_targets))
    for delete_target in delete_targets:
        if not (
            is_valid_bento_tag(delete_target) or is_valid_bento_name(delete_target)
        ):
            raise click.BadParameter(
                f'Bad formatting: "{delete_target}". Please present a valid bento bundle name or "name:version" tag. For list of bento bundles, separate delete targets by ",", for example: "my_service:v1,my_service:v2,classifier"'
            )
    return delete_targets


@inject
def import_bento(
    path: str,
    input_format: str | None = None,
    *,
    protocol: str | None = None,
    user: str | None = None,
    passwd: str | None = None,
    params: t.Optional[t.Dict[str, str]] = None,
    subpath: str | None = None,
    _bento_store: "BentoStore" = Provide[BentoMLContainer.bento_store],
) -> Bento:
    """
    Import a bento.

    Examples:

    .. code-block:: python

        # imports 'my_bento' from '/path/to/folder/my_bento.bento'
        bentoml.import_bento('/path/to/folder/my_bento.bento')

        # imports 'my_bento' from '/path/to/folder/my_bento.tar.gz'
        # currently supported formats are tar.gz ('gz'),
        # tar.xz ('xz'), tar.bz2 ('bz2'), and zip
        bentoml.import_bento('/path/to/folder/my_bento.tar.gz')
        # treats 'my_bento.ext' as a gzipped tarfile
        bentoml.import_bento('/path/to/folder/my_bento.ext', 'gz')

        # imports 'my_bento', which is stored as an
        # uncompressed folder, from '/path/to/folder/my_bento/'
        bentoml.import_bento('/path/to/folder/my_bento', 'folder')

        # imports 'my_bento' from the S3 bucket 'my_bucket',
        # path 'folder/my_bento.bento'
        # requires `fs-s3fs <https://pypi.org/project/fs-s3fs/>`_
        bentoml.import_bento('s3://my_bucket/folder/my_bento.bento')
        bentoml.import_bento('my_bucket/folder/my_bento.bento', protocol='s3')
        bentoml.import_bento('my_bucket', protocol='s3',
                             subpath='folder/my_bento.bento')
        bentoml.import_bento('my_bucket', protocol='s3',
                             subpath='folder/my_bento.bento',
                             user='<AWS access key>', passwd='<AWS secret key>',
                             params={'acl': 'public-read',
                                     'cache-control': 'max-age=2592000,public'})

    For a more comprehensive description of what each of the keyword arguments
    (:code:`protocol`, :code:`user`, :code:`passwd`,
     :code:`params`, and :code:`subpath`) mean, see the
    `FS URL documentation <https://docs.pyfilesystem.org/en/latest/openers.html>`_.

    Args:
        tag: the tag of the bento to export
        path: can be one of two things:
              * a folder on the local filesystem
              * an `FS URL <https://docs.pyfilesystem.org/en/latest/openers.html>`_,
                for example :code:`'s3://my_bucket/folder/my_bento.bento'`
        protocol: (expert) The FS protocol to use when exporting. Some example protocols
                  are :code:`'ftp'`, :code:`'s3'`, and :code:`'userdata'`
        user: (expert) the username used for authentication if required, e.g. for FTP
        passwd: (expert) the username used for authentication if required, e.g. for FTP
        params: (expert) a map of parameters to be passed to the FS used for
                export, e.g. :code:`{'proxy': 'myproxy.net'}` for setting a
                proxy for FTP
        subpath: (expert) the path inside the FS that the bento should be exported to
        _bento_store: the bento store to save the bento to

    Returns:
        Bento: the imported bento
    """
    return Bento.import_from(
        path,
        input_format,
        protocol=protocol,
        user=user,
        passwd=passwd,
        params=params,
        subpath=subpath,
    ).save(_bento_store)


@inject
def build_bentofile(
    bentofile: str | None = None,
    *,
    service: str | None = None,
    name: str | None = None,
    version: str | None = None,
    labels: dict[str, str] | None = None,
    build_ctx: str | None = None,
    platform: str | None = None,
    bare: bool = False,
    reload: bool = False,
    args: dict[str, t.Any] | None = None,
    _bento_store: BentoStore = Provide[BentoMLContainer.bento_store],
) -> Bento:
    """
    Build a Bento base on options specified in a bentofile.yaml file.

    By default, this function will look for a `bentofile.yaml` file in current working
    directory.

    Args:
        bentofile: The file path to build config yaml file
        version: Override the default auto generated version str
        build_ctx: Build context directory, when used as
        bare: whether to build a bento without copying files
        reload: whether to reload the service

    Returns:
        Bento: a Bento instance representing the materialized Bento saved in BentoStore
    """
    if args is not None:
        set_arguments(**args)
    if bentofile:
        try:
            bentofile = resolve_user_filepath(bentofile, None)
        except FileNotFoundError:
            raise InvalidArgument(f'bentofile "{bentofile}" not found')
        else:
            build_config = BentoBuildConfig.from_file(bentofile)
    else:
        for filename in DEFAULT_BENTO_BUILD_FILES:
            try:
                bentofile = resolve_user_filepath(filename, build_ctx)
            except FileNotFoundError:
                pass
            else:
                build_config = BentoBuildConfig.from_file(bentofile)
                break
        else:
            build_config = BentoBuildConfig(service=service or "")

    new_attrs: dict[str, t.Any] = {}
    if name is not None:
        new_attrs["name"] = name
    if labels:
        # Ensure both dictionaries are of type dict[str, str]
        existing_labels: dict[str, str] = build_config.labels or {}
        new_attrs["labels"] = {**existing_labels, **labels}

    if new_attrs:
        build_config = attr.evolve(build_config, **new_attrs)

    bento = Bento.create(
        build_config=build_config,
        version=version,
        build_ctx=build_ctx,
        platform=platform,
        bare=bare,
        reload=reload,
    )
    if not bare:
        return bento.save(_bento_store)
    return bento


def bento_management_commands() -> click.Group:
    import bentoml
    from bentoml import Tag
    from bentoml._internal.configuration import get_quiet_mode
    from bentoml._internal.configuration.containers import BentoMLContainer
    from bentoml._internal.utils import human_readable_size
    from bentoml_cli.utils import BentoMLCommandGroup

    @click.group(cls=BentoMLCommandGroup)
    def bentos():
        """Commands for managing Bento bundles."""
        pass

    @bentos.command()
    @click.argument("bento_tag", type=click.STRING)
    @click.option(
        "-o",
        "--output",
        type=click.Choice(["json", "yaml", "path"]),
        default="yaml",
    )
    @inject
    def get(
        bento_tag: str,
        output: str,
        bento_store: BentoStore = Provide[BentoMLContainer.bento_store],
    ) -> None:  # type: ignore
        """Print Bento details by providing the bento_tag.

        \b
        bentoml get iris_classifier:qojf5xauugwqtgxi
        bentoml get iris_classifier:qojf5xauugwqtgxi --output=json
        """
        bento = bento_store.get(bento_tag)

        if output == "path":
            rich.print(bento.path)
        elif output == "json":
            info = json.dumps(bento.info.to_dict(), indent=2, default=str)
            rich.print_json(info)
        else:
            info = yaml.dump(bento.info.to_dict(), indent=2, sort_keys=False)
            rich.print(Syntax(info, "yaml", background_color="default"))

    @bentos.command(name="list")
    @click.argument("bento_name", type=click.STRING, required=False)
    @click.option(
        "-o",
        "--output",
        type=click.Choice(["json", "yaml", "table"]),
        default="table",
    )
    @inject
    def list_bentos(
        bento_name: str,
        output: str,
        bento_store: BentoStore = Provide[BentoMLContainer.bento_store],
    ) -> None:  # type: ignore
        """List Bentos in local store

        \b
        # show all bentos saved
        $ bentoml list

        \b
        # show all versions of bento with the name FraudDetector
        $ bentoml list FraudDetector
        """
        bentos = bento_store.list(bento_name)
        res: list[dict[str, str]] = []
        for bento in sorted(bentos, key=lambda x: x.info.creation_time, reverse=True):
            bento_size = bento.file_size
            model_size = bento.total_size() - bento_size
            res.append(
                {
                    "tag": str(bento.tag),
                    "size": human_readable_size(bento_size),
                    "model_size": human_readable_size(model_size),
                    "creation_time": bento.info.creation_time.astimezone().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
            )

        if output == "json":
            info = json.dumps(res, indent=2)
            rich.print(info)
        elif output == "yaml":
            info = t.cast(str, yaml.safe_dump(res, indent=2))
            rich.print(Syntax(info, "yaml", background_color="default"))
        else:
            table = Table(box=None)
            table.add_column("Tag")
            table.add_column("Size")
            table.add_column("Model Size")
            table.add_column("Creation Time")
            for bento in res:
                table.add_row(
                    bento["tag"],
                    bento["size"],
                    bento["model_size"],
                    bento["creation_time"],
                )
            rich.print(table)

    @bentos.command()
    @click.argument(
        "delete_targets",
        nargs=-1,
        callback=parse_delete_targets_argument_callback,
        required=True,
    )
    @click.option(
        "-y",
        "--yes",
        "--assume-yes",
        is_flag=True,
        help="Skip confirmation when deleting a specific bento bundle",
    )
    @inject
    def delete(
        delete_targets: list[str],
        yes: bool,
        bento_store: BentoStore = Provide[BentoMLContainer.bento_store],
    ) -> None:  # type: ignore
        """Delete Bento in local bento store.

        \b
        Examples:
            * Delete single bento bundle by "name:version", e.g: `bentoml delete IrisClassifier:v1`
            * Bulk delete all bento bundles with a specific name, e.g.: `bentoml delete IrisClassifier`
            * Bulk delete multiple bento bundles by name and version, separated by ",", e.g.: `bentoml delete Irisclassifier:v1,MyPredictService:v2`
            * Bulk delete multiple bento bundles by name and version, separated by " ", e.g.: `bentoml delete Irisclassifier:v1 MyPredictService:v2`
            * Bulk delete without confirmation, e.g.: `bentoml delete IrisClassifier --yes`
        """

        def delete_target(target: str) -> None:
            tag = Tag.from_str(target)

            if tag.version is None:
                to_delete_bentos = bento_store.list(target)
            else:
                to_delete_bentos = [bento_store.get(tag)]

            for bento in to_delete_bentos:
                if yes:
                    delete_confirmed = True
                else:
                    delete_confirmed = click.confirm(f"delete bento {bento.tag}?")

                if delete_confirmed:
                    bento_store.delete(bento.tag)
                    rich.print(f"{bento} deleted.")

        for target in delete_targets:
            delete_target(target)

    @bentos.command()
    @click.argument("bento_tag", type=click.STRING)
    @click.argument(
        "out_path",
        type=click.STRING,
        default="",
        required=False,
    )
    @inject
    def export(
        bento_tag: str,
        out_path: str,
        bento_store: BentoStore = Provide[BentoMLContainer.bento_store],
    ) -> None:  # type: ignore
        """Export a Bento to an external file archive

        \b
        Arguments:
            BENTO_TAG: bento identifier
            OUT_PATH: output path of exported bento.

        If out_path argument is not provided, bento is exported to name-version.bento in the current directory.
        Beside the native .bento format, we also support ('tar'), tar.gz ('gz'), tar.xz ('xz'), tar.bz2 ('bz2'), and zip.

        \b
        Examples:
            bentoml export FraudDetector:20210709_DE14C9
            bentoml export FraudDetector:20210709_DE14C9 ./my_bento.bento
            bentoml export FraudDetector:latest ./my_bento.bento
            bentoml export FraudDetector:latest s3://mybucket/bentos/my_bento.bento
        """
        bento = bento_store.get(bento_tag)
        out_path = bento.export(out_path)
        rich.print(f"{bento} exported to {out_path}.")

    @bentos.command(name="import")
    @click.argument("bento_path", type=click.STRING)
    def import_bento_(bento_path: str) -> None:  # type: ignore
        """Import a previously exported Bento archive file

        \b
        Arguments:
            BENTO_PATH: path of Bento archive file

        \b
        Examples:
            bentoml import ./my_bento.bento
            bentoml import s3://mybucket/bentos/my_bento.bento
        """
        bento = import_bento(bento_path)
        rich.print(f"{bento} imported.")

    @bentos.command()
    @click.argument("bento_tag", type=click.STRING)
    @click.option(
        "-f",
        "--force",
        is_flag=True,
        default=False,
        help="Force pull from remote Bento store to local and overwrite even if it already exists in local",
    )
    @click.option("--with-models", is_flag=True, default=False, help="Pull models too")
    @inject
    def pull(
        bento_tag: str,
        force: bool,
        with_models: bool,
        cloud_client: BentoCloudClient = Provide[BentoMLContainer.bentocloud_client],
    ) -> None:  # type: ignore
        """Pull Bento from a remote Bento store server."""
        cloud_client.bento.pull(bento_tag, force=force, with_models=with_models)

    @bentos.command()
    @click.argument("bento_tag", type=click.STRING)
    @click.option(
        "-f",
        "--force",
        is_flag=True,
        default=False,
        help="Forced push to remote Bento store even if it exists in remote",
    )
    @click.option(
        "-t",
        "--threads",
        default=10,
        help="Number of threads to use for upload",
    )
    @inject
    def push(
        bento_tag: str,
        force: bool,
        threads: int,
        bento_store: BentoStore = Provide[BentoMLContainer.bento_store],
        cloud_client: BentoCloudClient = Provide[BentoMLContainer.bentocloud_client],
    ) -> None:  # type: ignore
        """Push Bento to a remote Bento store server."""
        bento_obj = bento_store.get(bento_tag)
        if not bento_obj:
            raise click.ClickException(f"Bento {bento_tag} not found in local store")
        cloud_client.bento.push(bento_obj, force=force, threads=threads)

    @bentos.command()
    @click.argument("build_ctx", type=click.Path(), default=".")
    @click.option(
        "-f", "--bentofile", help="Path to bentofile. Default to 'bentofile.yaml'"
    )
    @click.option(
        "--version",
        type=click.STRING,
        default=None,
        help="Bento version. By default the version will be generated.",
    )
    @click.option(
        "--label",
        "labels",
        type=click.STRING,
        multiple=True,
        help="(multiple)Bento labels",
        metavar="KEY=VALUE",
    )
    @click.option(
        "-o",
        "--output",
        type=click.Choice(["tag", "default"]),
        default="default",
        show_default=True,
        help="Output log format. '-o tag' to display only bento tag.",
    )
    @cog.optgroup.group(cls=cog.MutuallyExclusiveOptionGroup, name="Utilities options")
    @cog.optgroup.option(
        "--containerize",
        default=False,
        is_flag=True,
        type=click.BOOL,
        help="Whether to containerize the Bento after building. '--containerize' is the shortcut of 'bentoml build && bentoml containerize'.",
    )
    @cog.optgroup.option(
        "--push",
        default=False,
        is_flag=True,
        type=click.BOOL,
        help="Whether to push the result bento to BentoCloud. Make sure to login with 'bentoml cloud login' first.",
    )
    @click.option(
        "--force", is_flag=True, default=False, help="Forced push to BentoCloud"
    )
    @click.option("--threads", default=10, help="Number of threads to use for upload")
    @click.option(
        "--platform",
        default=None,
        help="Platform to build for",
        type=click.Choice(ALLOWED_PLATFORMS),
    )
    def build(  # type: ignore
        build_ctx: str,
        bentofile: str | None,
        version: str | None,
        labels: tuple[str, ...],
        output: t.Literal["tag", "default"],
        push: bool,
        force: bool,
        threads: int,
        containerize: bool,
        platform: str | None,
    ):
        """Build a new Bento from current directory."""
        from bentoml._internal.configuration import set_quiet_mode
        from bentoml._internal.log import configure_logging

        if output == "tag":
            set_quiet_mode()
            configure_logging()

        labels_dict: dict[str, t.Any] = {}
        for label in labels:
            key, label_value = label.split("=", 1)
            labels_dict[key] = label_value

        service: str | None = None
        if ":" in build_ctx:
            service = build_ctx
            build_ctx = "."

        bento = build_bentofile(
            bentofile,
            service=service,
            version=version,
            labels=labels_dict or None,
            build_ctx=build_ctx,
            platform=platform,
        )

        containerize_cmd = f"dynamo containerize {bento.tag}"
        # push_cmd = f"dynamo push {bento.tag}"

        # NOTE: Don't remove the return statement here, since we will need this
        # for usage stats collection if users are opt-in.
        if output == "tag":
            rich.print(f"__tag__:{bento.tag}")
        else:
            if not get_quiet_mode():
                rich.print(DYNAMO_FIGLET)
                rich.print(f"[green]Successfully built {bento.tag}.")
                next_steps = []
                if not containerize:
                    next_steps.append(
                        "\n\n* Containerize your Bento with `dynamo containerize`:\n"
                        f"    $ {containerize_cmd} [or dynamo build --containerize]"
                    )
                # if not push:
                #     next_steps.append(
                #         "\n\n* Push to BentoCloud with `bentoml push`:\n"
                #         f"    $ {push_cmd} [or bentoml build --push]"
                #     )

                if next_steps:
                    rich.print(f"\n[blue]Next steps: {''.join(next_steps)}[/]")
        if push:
            if not get_quiet_mode():
                rich.print(f"\n[magenta]Pushing {bento} to BentoCloud...[/]")
            cloud_client = BentoMLContainer.bentocloud_client.get()
            cloud_client.bento.push(bento, force=force, threads=threads)
        elif containerize:
            backend: DefaultBuilder = t.cast(
                "DefaultBuilder", os.getenv("BENTOML_CONTAINERIZE_BACKEND", "docker")
            )
            try:
                bentoml.container.health(backend)
            except subprocess.CalledProcessError:
                raise bentoml.exceptions.BentoMLException(
                    f"Backend {backend} is not healthy"
                )
            bentoml.container.build(bento.tag, backend=backend)

        return bento

    return bentos


bento_command = bento_management_commands()
