"""Independent regression for the pinned gVisor dispatcher eventfd leak."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pipeline_fd', Path(__file__).with_name('pipeline.py'))
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

READ = 'func (d *readVDispatcher) release() {\n\td.buf.release()\n\td.mgr.close()\n}'
RECV = 'func (d *recvMMsgDispatcher) release() {\n\tfor _, iov := range d.bufs {\n\t\tiov.release()\n\t}\n\td.mgr.close()\n}'

class GVisorFDTests(unittest.TestCase):
    def test_both_dispatchers_close_owned_eventfd_after_release(self):
        patched = pipeline.patch_gvisor_dispatchers(READ + '\n\n' + RECV)
        self.assertEqual(patched.count('defer unix.Close(d.EFD)'), 2)
        self.assertNotIn('unix.Close(d.fd)', patched)  # TUN belongs to sing-tun.
        for dispatcher in ['readVDispatcher', 'recvMMsgDispatcher']:
            self.assertIn('func (d *' + dispatcher + ') release() {\n\tdefer unix.Close(d.EFD)', patched)

    def test_unknown_or_partially_patched_source_is_rejected(self):
        for text in ['', READ, RECV, READ * 2 + RECV, READ + RECV * 2,
                     (READ + RECV).replace('d.mgr.close()', 'd.mgr.stop()', 1)]:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                pipeline.patch_gvisor_dispatchers(text)
        patched = pipeline.patch_gvisor_dispatchers(READ + RECV)
        with self.assertRaises(RuntimeError):
            pipeline.patch_gvisor_dispatchers(patched)

if __name__ == '__main__':
    unittest.main()
