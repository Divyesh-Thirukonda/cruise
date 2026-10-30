"""Synthetic command audio and mocked HTTP; no room audio or live billing."""
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
import urllib.error

from modulate.agent import Ledger, AgentError
from modulate.transcription import MuseTranscriber, decode_pcm, MODEL, MAX_PCM
from modulate.voice import VoiceListener, Utterance, VoiceError


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.env = patch.dict(os.environ, {'MODULATE_ASR_PROVIDER':'meta_muse',
            'MODULATE_CLOUD_URL':'https://modulate-connect.vercel.app/api/modulate-provider',
            'MODULATE_CLOUD_KEY':'test_'+'x'*40}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.ledger = Ledger(Path(self.root.name)/'budget.json', 50)
        self.asr = MuseTranscriber(self.ledger)
        self.asr.opener = MagicMock()
        self.audio = {'pcm':base64.b64encode(bytes(64000)).decode()}
        self.asr.opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            {'model':MODEL,'transcript':'Make the coins red.','audioDurationMs':2000}).encode()

    def test_reserves_shared_budget_before_dispatch_and_only_forwards_gateway_key(self):
        def dispatch(*args, **kwargs):
            self.assertEqual(self.ledger.status()['charged_or_reserved_dollars'], .0001)
            return self.asr.opener.open.return_value
        self.asr.opener.open.side_effect = dispatch
        access = Mock()
        result = self.asr.transcribe(self.audio, access)
        self.assertEqual(result['text'], 'Make the coins red.')
        self.assertEqual(access.call_count, 3)
        request = self.asr.opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith('?action=transcribe'))
        self.assertTrue(base64.b64decode(json.loads(request.data)['wav']).startswith(b'RIFF'))
        self.assertEqual(self.ledger.data['calls'][0]['status'],'settled')

    def test_actual_muse_frame_padding_is_accepted_without_under_reserving_cost(self):
        self.asr.opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(
            {'model':MODEL,'transcript':'','audioDurationMs':1040}).encode()
        result=self.asr.transcribe({'pcm':base64.b64encode(bytes(32000)).decode()},Mock())
        self.assertEqual(result['audio_ms'],1000)
        self.assertEqual(self.ledger.data['calls'][0]['charged'],50)
        self.assertEqual(self.ledger.data['calls'][0]['status'],'settled')

    def test_failure_retains_hold_and_never_retries_or_logs_provider_body(self):
        self.asr.opener.open.side_effect = urllib.error.HTTPError('https://example',429,'secret',{},io.BytesIO(b'private'))
        with self.assertRaisesRegex(AgentError,'request discarded') as error:
            self.asr.transcribe(self.audio, Mock())
        self.assertNotIn('secret',str(error.exception)); self.assertNotIn('private',str(error.exception))
        self.assertEqual(self.asr.opener.open.call_count,1)
        self.assertEqual(self.ledger.data['calls'][0]['status'],'reserved')

    def test_permission_and_budget_failures_prevent_network(self):
        with self.assertRaises(AgentError):
            self.asr.transcribe(self.audio, Mock(side_effect=AgentError('off')))
        self.ledger.limit = 0
        with self.assertRaises(AgentError): self.asr.transcribe(self.audio,Mock())
        self.asr.opener.open.assert_not_called()

    def test_revocation_during_transcription_discards_result_and_keeps_accounting(self):
        with self.assertRaisesRegex(AgentError,'revoked'):
            self.asr.transcribe(self.audio,Mock(side_effect=[None,None,AgentError('revoked')]))
        self.assertEqual(self.ledger.data['calls'][0]['status'],'settled')

    def test_invalid_or_oversized_audio_is_rejected_before_reservation(self):
        for data in ({}, {'pcm':'***'}, {'pcm':'YQ=='}, {'pcm':''},
                     {'pcm':base64.b64encode(bytes(MAX_PCM+2)).decode()}, {**self.audio,'url':'https://other'}):
            with self.subTest(size=len(str(data))),self.assertRaises(AgentError): decode_pcm(data)
        self.assertEqual(self.ledger.status()['calls'],0)

    def test_malformed_transcript_or_duration_does_not_release_hold(self):
        for result in ({'transcript':'x'*2001,'audioDurationMs':2000},
                       {'transcript':'hello','audioDurationMs':0}, {'transcript':None,'audioDurationMs':2000}):
            self.asr.opener.open.return_value.__enter__.return_value.read.return_value=json.dumps({'model':MODEL,**result}).encode()
            with self.assertRaises(AgentError):self.asr.transcribe(self.audio,Mock())
        self.assertTrue(all(x['status']=='reserved' for x in self.ledger.data['calls']))


class InvokedVoiceTests(unittest.TestCase):
    def listener(self):
        listener=VoiceListener(Mock(),Mock(),command_transcribe=Mock(return_value='Make a game'))
        listener._transcribe=Mock(return_value='A conversation in the room')
        listener.set_transcription_provider('meta_muse')
        return listener

    def test_ambient_and_media_never_use_cloud(self):
        voice=self.listener()
        for utterance in (Utterance(b'\0\0',1),Utterance(b'\0\0',1,'Hey Meta stop',True,playback_wake=True)):
            voice._command_text(utterance,False,voice._epoch)
        voice.command_transcribe.assert_not_called()

    def test_wake_ptt_and_followup_use_cloud_even_with_cached_local_transcript(self):
        voice=self.listener()
        for utterance,ptt in ((Utterance(b'\0\0',1,'Hey Meta make a game',True),False),
                              (Utterance(b'\0\0',1),True),
                              (Utterance(b'\0\0',1,followup_id='a'*32),False)):
            self.assertEqual(voice._command_text(utterance,ptt,voice._epoch),'Make a game')
        self.assertEqual(voice.command_transcribe.call_count,3)

    def test_busy_cancel_stale_epoch_and_disabled_provider_cannot_upload(self):
        voice=self.listener();utterance=Utterance(b'\0\0',1,'Hey Meta cancel',True)
        voice.set_busy(True);voice._command_text(utterance,False,voice._epoch)
        self.assertIsNone(voice._command_text(utterance,False,voice._epoch-1))
        voice.set_busy(False);voice.set_transcription_provider('local')
        voice._command_text(utterance,False,voice._epoch)
        voice.command_transcribe.assert_not_called()

    def test_final_local_wake_check_can_gate_muse_and_preserve_omitted_wake_words(self):
        voice=self.listener();voice._transcribe.return_value='Hey Meta make a game'
        text=voice._command_text(Utterance(b'\0\0',1),False,voice._epoch)
        self.assertEqual(text,'Hey Meta, Make a game')

    def test_cloud_failure_does_not_fall_back_to_unconfirmed_local_command(self):
        voice=self.listener();voice.command_transcribe.side_effect=RuntimeError('private')
        with self.assertRaisesRegex(VoiceError,'request discarded'):
            voice._command_text(Utterance(b'\0\0',1,'Hey Meta make a game',True),False,voice._epoch)

    def test_permission_epoch_change_during_upload_never_delivers_late_command(self):
        voice=self.listener()
        voice.set_enabled(True)
        utterance=Utterance(b'\0\0',1,'Hey Meta make a game',True)
        epoch=voice._epoch
        def delayed(_):
            voice.set_enabled(False)
            return 'Make a game'
        voice.command_transcribe.side_effect=delayed
        text=voice._command_text(utterance,False,epoch)
        voice._deliver(text,utterance,False,epoch)
        voice.on_request.assert_not_called()
