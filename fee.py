from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.system_program import TransferParams, transfer

FEE_WALLET = Pubkey.from_string("7BSUBgKUF3Ju735r24BLvmES2gDeZnP6ukPJbno3PkyN")  # ඔබේ fee wallet address එකක් දාන්න

async def create_fee_instruction(sender_pubkey: Pubkey, lamports: int) -> Instruction | None:
    fee_amount = int(lamports * 0.01)  # 1% fee
    if fee_amount == 0:
        return None

    fee_instruction = transfer(
        TransferParams(
            from_pubkey=sender_pubkey,
            to_pubkey=FEE_WALLET,
            lamports=fee_amount
        )
    )
    return fee_instruction

