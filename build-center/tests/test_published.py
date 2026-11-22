import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.check_updates import already_published
from ci.published import matching_release
from center_core import CenterError


class PublishedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.plan={'release_tag':'s928b-ezjb-suki35004-checked','firmware':'S928BXXU6EZJB',
                   'sukisu_commit':'a'*40,'susfs_commit':'b'*40}
        self.release={'tag_name':self.plan['release_tag']+'-r123',
                      'body':'SukiSU commit: '+'a'*40+'\nSuSFS commit: '+'b'*40,
                      'assets':[{'name':'build-plan.json'},
                                {'name':'S928BXXU6EZJB-EUX-AnyKernel3.zip','digest':'sha256:'+'c'*64}]}

    def test_forced_release_is_found_when_the_normal_tag_does_not_exist(self):
        def get(url,*args):
            if '/tags/' in url:raise CenterError('nicht gefunden')
            return {'data':[self.release]}
        self.assertTrue(already_published('owner/repo',self.plan,get=get))

    def test_unrelated_or_incomplete_releases_cannot_suppress_a_build(self):
        for field in ('draft','tag','pin','firmware','digest','plan'):
            release=copy.deepcopy(self.release)
            if field=='draft':release['draft']=True
            if field=='tag':release['tag_name']+='extra'
            if field=='pin':release['body']=release['body'].replace('a'*40,'d'*40)
            if field=='firmware':release['assets'][1]['name']='S928BXXS6EZJ1-EUX-AnyKernel3.zip'
            if field=='digest':release['assets'][1]['digest']=''
            if field=='plan':release['assets'].pop(0)
            with self.subTest(field=field):self.assertFalse(matching_release(release,self.plan))

    def test_a_complete_normal_release_avoids_the_listing(self):
        self.release['tag_name']=self.plan['release_tag']
        def get(url,*args):
            self.assertIn('/tags/',url)
            return {'data':self.release}
        self.assertTrue(already_published('owner/repo',self.plan,get=get))

    def test_api_permission_or_limit_errors_are_not_treated_as_a_ready_kernel(self):
        def get(*args):raise CenterError('API-Limit erreicht')
        with self.assertRaisesRegex(CenterError,'API-Limit'):
            already_published('owner/repo',self.plan,get=get)


if __name__=='__main__':unittest.main()
