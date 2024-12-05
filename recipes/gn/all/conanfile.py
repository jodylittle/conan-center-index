import os
import shutil
import sys
import textwrap

from conan import ConanFile
from conan.tools.apple import is_apple_os, XCRun
from conan.tools.build import check_min_cppstd
from conan.tools.env import VirtualBuildEnv, Environment
from conan.tools.files import chdir, copy, get, load, save, replace_in_file
from conan.tools.layout import basic_layout
from conan.tools.microsoft import is_msvc, VCVars
from conan.tools.scm import Version

required_conan_version = ">=2.0.9"


class GnConan(ConanFile):
    name = "gn"
    description = "GN is a meta-build system that generates build files for Ninja."
    license = "BSD-3-Clause"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://gn.googlesource.com/"
    topics = ("build system", "ninja")

    package_type = "application"
    settings = "os", "arch", "compiler", "build_type"

    def layout(self):
        basic_layout(self, src_folder="src")

    def package_id(self):
        del self.info.settings.compiler

    @property
    def _min_cppstd(self):
        if Version(self.version) == "cci.20210429":
            return 17
        else:
            return 20

    def validate_build(self):
        check_min_cppstd(self, self._min_cppstd)

    def build_requirements(self):
        # FIXME: add cpython build requirements for `build/gen.py`.
        self.tool_requires("ninja/1.11.1")

    def source(self):
        get(self, **self.conan_data["sources"][self.version])

    @property
    def _gn_platform(self):
        if is_apple_os(self):
            return "darwin"
        if is_msvc(self):
            return "msvc"
        # Assume gn knows about the os
        return str(self.settings.os).lower()

    @property
    def _cxx(self):
        compilers_by_conf = self.conf.get("tools.build:compiler_executables", default={}, check_type=dict)
        cxx = compilers_by_conf.get("cpp") or VirtualBuildEnv(self).vars().get("CXX")
        if cxx:
            return cxx
        if self.settings.compiler == "apple-clang":
            return XCRun(self).cxx
        compiler_version = self.settings.compiler.version
        major = Version(compiler_version).major
        if self.settings.compiler == "gcc":
            return shutil.which(f"g++-{compiler_version}") or shutil.which(f"g++-{major}") or shutil.which("g++") or ""
        if self.settings.compiler == "clang":
            return shutil.which(f"clang++-{compiler_version}") or shutil.which(f"clang++-{major}") or shutil.which("clang++") or ""
        return ""

    def generate(self):
        env = VirtualBuildEnv(self)
        env.generate()

        # Make sure CXX env var is set, otherwise gn defaults it to clang++
        # https://gn.googlesource.com/gn/+/refs/heads/main/build/gen.py#386
        env = Environment()
        env.define("CXX", self._cxx)

        if is_apple_os(self) and self.settings.arch:
            arch_flags = ""
            if "armv8" in self.settings.arch:
                arch_flags += "-arch arm64 "
            if "x86_64" in self.settings.arch:
                arch_flags += "-arch x86_64 "

            env.append("CFLAGS", arch_flags)
            env.append("LDFLAGS", arch_flags)

        env.vars(self).save_script("conanbuild_gn")

        if is_msvc(self):
            vcvars = VCVars(self)
            vcvars.generate()

        configure_args = [
            "--no-last-commit-position",
            f"--host={self._gn_platform}",
        ]
        if self.settings.build_type in ["Debug", "RelWithDebInfo"]:
            configure_args.append("-d")
        save(self, os.path.join(self.source_folder, "configure_args"), " ".join(configure_args))

    def build(self):
        with chdir(self, self.source_folder):
            # Generate dummy header to be able to run `build/gen.py` with `--no-last-commit-position`.
            # This allows running the script without the tree having to be a git checkout.
            save(self, os.path.join(self.source_folder, "src", "gn", "last_commit_position.h"),
                textwrap.dedent("""\
                    #pragma once
                    #define LAST_COMMIT_POSITION "1"
                    #define LAST_COMMIT_POSITION_NUM 1
                    """),
            )

            # Disable GenerateLastCommitPosition()
            replace_in_file(self, os.path.join(self.source_folder, "build/gen.py"),
                            "def GenerateLastCommitPosition(host, header):",
                            "def GenerateLastCommitPosition(host, header):\n  return")

            self.run(f"{sys.executable} build/gen.py " + load(self, "configure_args"))
            self.run(f"ninja -C out -j{os.cpu_count()} -v")

    def package(self):
        copy(self, "LICENSE", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
        if self.settings.os == "Windows":
            copy(self, "gn.exe",
                 src=os.path.join(self.source_folder, "out"),
                 dst=os.path.join(self.package_folder, "bin"))
        else:
            copy(self, "gn",
                 src=os.path.join(self.source_folder, "out"),
                 dst=os.path.join(self.package_folder, "bin"))

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.frameworkdirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.resdirs = []
