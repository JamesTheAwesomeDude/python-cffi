import py
import sys, os, re
import shutil, subprocess, time
from testing.udir import udir
import cffi


local_dir = os.path.dirname(os.path.abspath(__file__))
_link_error = '?'

def check_lib_python_found(tmpdir):
    global _link_error
    if _link_error == '?':
        ffi = cffi.FFI()
        kwds = {}
        ffi._apply_embedding_fix(kwds)
        ffi.set_source("_test_lib_python_found", "", **kwds)
        try:
            ffi.compile(tmpdir=tmpdir, verbose=True)
        except cffi.VerificationError as e:
            _link_error = e
        else:
            _link_error = None
    if _link_error:
        py.test.skip(str(_link_error))


def prefix_pythonpath():
    cffi_base = os.path.dirname(os.path.dirname(local_dir))
    pythonpath = os.environ.get('PYTHONPATH', '').split(os.pathsep)
    if cffi_base not in pythonpath:
        pythonpath.insert(0, cffi_base)
    return os.pathsep.join(pythonpath)


class EmbeddingTests:
    _compiled_modules = {}

    def setup_method(self, meth):
        check_lib_python_found(str(udir.ensure('embedding', dir=1)))
        self._path = udir.join('embedding', meth.__name__)
        if sys.platform == "win32" or sys.platform == "darwin":
            self._compiled_modules.clear()   # workaround

    def get_path(self):
        return str(self._path.ensure(dir=1))

    def _run_base(self, args, env_extra={}, **kwds):
        print('RUNNING:', args, env_extra, kwds)
        env = os.environ.copy()
        env.update(env_extra)
        return subprocess.Popen(args, env=env, **kwds)

    def _run(self, args, env_extra={}):
        popen = self._run_base(args, env_extra, cwd=self.get_path(),
                                 stdout=subprocess.PIPE,
                                 universal_newlines=True)
        output = popen.stdout.read()
        err = popen.wait()
        if err:
            raise OSError("popen failed with exit code %r: %r" % (
                err, args))
        print(output.rstrip())
        return output

    def prepare_module(self, name):
        if name not in self._compiled_modules:
            path = self.get_path()
            filename = '%s.py' % name
            # NOTE: if you have an .egg globally installed with an older
            # version of cffi, this will not work, because sys.path ends
            # up with the .egg before the PYTHONPATH entries.  I didn't
            # find a solution to that: we could hack sys.path inside the
            # script run here, but we can't hack it in the same way in
            # execute().
            env_extra = {'PYTHONPATH': prefix_pythonpath()}
            output = self._run([sys.executable, os.path.join(local_dir, filename)],
                               env_extra=env_extra)
            match = re.compile(r"\bFILENAME: (.+)").search(output)
            assert match
            dynamic_lib_name = match.group(1)
            if sys.platform == 'win32':
                assert dynamic_lib_name.endswith('_cffi.dll')
            elif sys.platform == 'darwin':
                assert dynamic_lib_name.endswith('_cffi.dylib')
            else:
                assert dynamic_lib_name.endswith('_cffi.so')
            self._compiled_modules[name] = dynamic_lib_name
        return self._compiled_modules[name]

    def compile(self, name, modules, opt=False, threads=False, defines={}):
        path = self.get_path()
        filename = '%s.c' % name
        shutil.copy(os.path.join(local_dir, filename), path)
        shutil.copy(os.path.join(local_dir, 'thread-test.h'), path)
        import distutils.ccompiler
        curdir = os.getcwd()
        try:
            os.chdir(self.get_path())
            c = distutils.ccompiler.new_compiler()
            print('compiling %s with %r' % (name, modules))
            extra_preargs = []
            if sys.platform == 'win32':
                libfiles = []
                for m in modules:
                    m = os.path.basename(m)
                    assert m.endswith('.dll')
                    libfiles.append('Release\\%s.lib' % m[:-4])
                modules = libfiles
                extra_preargs.append('/MANIFEST')
            elif threads:
                extra_preargs.append('-pthread')
            objects = c.compile([filename], macros=sorted(defines.items()), debug=True)
            c.link_executable(objects + modules, name, extra_preargs=extra_preargs)
        finally:
            os.chdir(curdir)

    def execute(self, name):
        path = self.get_path()
        env_extra = {'PYTHONPATH': prefix_pythonpath()}
        libpath = os.environ.get('LD_LIBRARY_PATH')
        if libpath:
            libpath = path + ':' + libpath
        else:
            libpath = path
        env_extra['LD_LIBRARY_PATH'] = libpath
        print('running %r in %r' % (name, path))
        executable_name = name
        if sys.platform == 'win32':
            executable_name = os.path.join(path, executable_name + '.exe')
        else:
            executable_name = os.path.join('.', executable_name)
        popen = self._run_base([executable_name], env_extra, cwd=path,
                               stdout=subprocess.PIPE,
                               universal_newlines=True)
        result = popen.stdout.read()
        err = popen.wait()
        if err:
            raise OSError("%r failed with exit code %r" % (name, err))
        return result


class TestBasic(EmbeddingTests):
    def test_basic(self):
        add1_cffi = self.prepare_module('add1')
        self.compile('add1-test', [add1_cffi])
        output = self.execute('add1-test')
        assert output == ("preparing...\n"
                          "adding 40 and 2\n"
                          "adding 100 and -5\n"
                          "got: 42 95\n")

    def test_two_modules(self):
        add1_cffi = self.prepare_module('add1')
        add2_cffi = self.prepare_module('add2')
        self.compile('add2-test', [add1_cffi, add2_cffi])
        output = self.execute('add2-test')
        assert output == ("preparing...\n"
                          "adding 40 and 2\n"
                          "prepADD2\n"
                          "adding 100 and -5 and -20\n"
                          "got: 42 75\n")