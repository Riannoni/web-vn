import copy
import unittest
from diagnostic_sprite_adapter_weight import prepare_candidate


def graph():
    return {
        '1': {'class_type': 'CheckpointLoaderSimple','inputs':{'ckpt_name': 'CyberRealisticPony_V18.0_F16.safetensors'}},
        '2': {'class_type':'EmptyLatentImage','inputs':{'width':832,'height':1216,'batch_size':1}},
        '3': {'class_type':'CLIPTextEncode','inputs':{'text':'SYNTHETIC_OUTFIT','clip':['1',1]}},
        '4': {'class_type':'KSampler','inputs':{'model':['9',0],'latent_image':['2',0],'seed':101,'denoise':1.0,'positive':['3',0]}},
        '5': {'class_type':'VAEDecode','inputs':{'samples':['4',0]}},
        '6': {'class_type':'SaveImage','inputs':{'images':['5',0],'filename_prefix':'baseline'}},
        '7': {'class_type':'LoadImage','inputs':{'image':'SYNTHETIC_FACE.png'}},
        '8': {'class_type':'IPAdapterModelLoader','inputs':{'ipadapter_file':'ip-adapter-plus-face_sdxl_vit-h.safetensors'}},
        '9': {'class_type':'IPAdapterAdvanced','inputs':{'model':['1',0],'ipadapter':['8',0],'image':['7',0],'weight':0.8}},
        '10': {'class_type':'CLIPVisionLoader','inputs':{'clip_name':'CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors'}}
    }


class CandidateTest(unittest.TestCase):
    def test_one_factor_and_routing_only(self):
        baseline=graph();before=copy.deepcopy(baseline)
        new,info=prepare_candidate(baseline,'private_renderer_diag_TEST0001')
        self.assertEqual(baseline,before)
        self.assertEqual(new['9']['inputs']['weight'],0.6)
        self.assertEqual(new['6']['inputs']['filename_prefix'],'private_renderer_diag_TEST0001')
        new['9']['inputs']['weight']=0.8
        new['6']['inputs']['filename_prefix']='baseline'
        self.assertEqual(new,baseline)
        self.assertEqual(info['seed'],101)

    def test_fails_closed_on_disconnected_adapter(self):
        g=graph();g['4']['inputs']['model']=['1',0]
        with self.assertRaisesRegex(ValueError,'adapter_not_consumed'):
            prepare_candidate(g,'private_renderer_diag_TEST0002')

    def test_fails_closed_on_body_seed(self):
        g=graph();g['4']['inputs']['latent_image']=['11',0]
        with self.assertRaisesRegex(ValueError,'body_seed'):
            prepare_candidate(g,'private_renderer_diag_TEST0003')

    def test_fails_closed_on_multi_adapter(self):
        g=graph();g['11']=copy.deepcopy(g['9'])
        with self.assertRaisesRegex(ValueError,'expected_one_IPAdapterAdvanced'):
            prepare_candidate(g,'private_renderer_diag_TEST0004')

    def test_fails_closed_on_output_prefix(self):
        with self.assertRaises(ValueError):
            prepare_candidate(graph(),'../../published')

    def test_fails_closed_on_unbounded_canvas(self):
        g=graph();g['2']['inputs']['width']=4096
        with self.assertRaisesRegex(ValueError,'unbounded_canvas'):
            prepare_candidate(g,'private_renderer_diag_TEST0005')


if __name__ == '__main__':
    unittest.main()
