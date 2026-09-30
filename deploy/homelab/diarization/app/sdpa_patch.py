"""Replace NeMo's FlexAttention with dense-mask SDPA so the graph is ONNX-exportable."""
import nemo.collections.asr.modules.transformer_encoder as te
import torch
import torch.nn.functional as F


class DenseMask:
    def __init__(self, m): self.m = m

def _create_block_mask(mask_mod, B, H, Q_LEN, KV_LEN, device=None, **kw):
    b = torch.arange(B, device=device).view(B, 1, 1, 1)
    h = torch.zeros(1, 1, 1, 1, dtype=torch.long, device=device)
    q = torch.arange(Q_LEN, device=device).view(1, 1, Q_LEN, 1)
    k = torch.arange(KV_LEN, device=device).view(1, 1, 1, KV_LEN)
    return DenseMask(mask_mod(b, h, q, k).expand(B, 1, Q_LEN, KV_LEN))

def _get_flex_attention(q):
    def attn(q, k, v, block_mask=None, score_mod=None, **kw):
        bias = getattr(score_mod, "_relative_position_bias", None) if score_mod is not None else None
        mask = block_mask.m if block_mask is not None else None
        if bias is not None:
            bias = bias.to(q.dtype)
            if mask is not None: bias = bias.masked_fill(~mask, float("-inf"))
            return F.scaled_dot_product_attention(q, k, v, attn_mask=bias)
        return F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
    return attn

def apply():
    te.create_block_mask = _create_block_mask
    te._transformer_utils._get_flex_attention = _get_flex_attention
