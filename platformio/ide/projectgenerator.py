# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import re
import sys
from os.path import abspath, basename, expanduser, isdir, isfile, join, relpath

import bottle
from click.testing import CliRunner

from platformio import exception, util
from platformio.commands.run import cli as cmd_run
from platformio.compat import PY2, WINDOWS, get_file_contents
from platformio.project.config import ProjectConfig
from platformio.project.helpers import (
    get_projectlib_dir, get_projectlibdeps_dir, get_projectsrc_dir)


class ProjectGenerator(object):

    def __init__(self, project_dir, ide, env_name):
        self.project_dir = project_dir
        self.ide = ide
        self.env_name = env_name

        self._tplvars = {}
        self._gather_tplvars()

    @staticmethod
    def get_supported_ides():
        tpls_dir = join(util.get_source_dir(), "ide", "tpls")
        return sorted(
            [d for d in os.listdir(tpls_dir) if isdir(join(tpls_dir, d))])

    @util.memoized()
    def get_project_env(self):
        data = {}
        config = ProjectConfig.get_instance(
            join(self.project_dir, "platformio.ini"))
        for env in config.envs():
            if self.env_name != env:
                continue
            data = config.items(env=env, as_dict=True)
            data['env_name'] = self.env_name
        return data

    def get_project_build_data(self):
        data = {
            "defines": [],
            "includes": [],
            "cxx_path": None,
            "prog_path": None
        }
        envdata = self.get_project_env()
        if not envdata:
            return data

        result = CliRunner().invoke(cmd_run, [
            "--project-dir", self.project_dir, "--environment",
            envdata['env_name'], "--target", "idedata"
        ])

        if result.exit_code != 0 and not isinstance(result.exception,
                                                    exception.ReturnErrorCode):
            raise result.exception
        if '"includes":' not in result.output:
            raise exception.PlatformioException(result.output)

        for line in result.output.split("\n"):
            line = line.strip()
            if line.startswith('{"') and line.endswith("}"):
                data = json.loads(line)
        return data

    def get_project_name(self):
        return basename(self.project_dir)

    def get_src_files(self):
        result = []
        with util.cd(self.project_dir):
            for root, _, files in os.walk(get_projectsrc_dir()):
                for f in files:
                    result.append(relpath(join(root, f)))
        return result

    def get_tpls(self):
        tpls = []
        tpls_dir = join(util.get_source_dir(), "ide", "tpls", self.ide)
        for root, _, files in os.walk(tpls_dir):
            for f in files:
                if not f.endswith(".tpl"):
                    continue
                _relpath = root.replace(tpls_dir, "")
                if _relpath.startswith(os.sep):
                    _relpath = _relpath[1:]
                tpls.append((_relpath, join(root, f)))
        return tpls

    def generate(self):
        for tpl_relpath, tpl_path in self.get_tpls():
            dst_dir = self.project_dir
            if tpl_relpath:
                dst_dir = join(self.project_dir, tpl_relpath)
                if not isdir(dst_dir):
                    os.makedirs(dst_dir)

            file_name = basename(tpl_path)[:-4]
            contents = self._render_tpl(tpl_path)
            self._merge_contents(
                join(dst_dir, file_name),
                contents.encode("utf8") if PY2 else contents)

    def _render_tpl(self, tpl_path):
        return bottle.template(get_file_contents(tpl_path), **self._tplvars)

    @staticmethod
    def _merge_contents(dst_path, contents):
        if basename(dst_path) == ".gitignore" and isfile(dst_path):
            return
        with open(dst_path, "w") as f:
            f.write(contents)

    def _gather_tplvars(self):
        self._tplvars.update(self.get_project_env())
        self._tplvars.update(self.get_project_build_data())
        with util.cd(self.project_dir):
            self._tplvars.update({
                "project_name": self.get_project_name(),
                "src_files": self.get_src_files(),
                "user_home_dir": abspath(expanduser("~")),
                "project_dir": self.project_dir,
                "project_src_dir": get_projectsrc_dir(),
                "project_lib_dir": get_projectlib_dir(),
                "project_libdeps_dir": get_projectlibdeps_dir(),
                "systype": util.get_systype(),
                "platformio_path": self._fix_os_path(
                    sys.argv[0] if isfile(sys.argv[0])
                    else util.where_is_program("platformio")),
                "env_pathsep": os.pathsep,
                "env_path": self._fix_os_path(os.getenv("PATH"))
            })  # yapf: disable

    @staticmethod
    def _fix_os_path(path):
        return (re.sub(r"[\\]+", '\\' * 4, path) if WINDOWS else path)
