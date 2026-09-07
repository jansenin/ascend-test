#pragma once

#ifdef ASCENDC_CPU_DEBUG
#include "cpu_debug_launch.h"
#endif
#include "kernel_operator.h"

namespace lab {

constexpr uint32_t kAddTile = 8192;
constexpr uint32_t kM = 256;
constexpr uint32_t kK = 64;
constexpr uint32_t kN = 256;
constexpr uint32_t kSingleCoreM = 128;
constexpr uint32_t kBaseM = 128;
constexpr uint32_t kBaseK = 64;
constexpr uint32_t kBaseN = 256;
constexpr uint32_t kCubeBlock = 16;

#if defined(__NPU_ARCH__) && (__NPU_ARCH__ == 3510)
template <typename T, uint32_t Length>
__simd_vf__ inline void AddRegisters(__ubuf__ T* dst, __ubuf__ T* lhs, __ubuf__ T* rhs)
{
    constexpr uint32_t elementsPerVector = AscendC::GetVecLen() / sizeof(T);
    constexpr uint32_t repeats = (Length + elementsPerVector - 1) / elementsPerVector;
    uint32_t remaining = Length;
    AscendC::Reg::RegTensor<T> lhsReg;
    AscendC::Reg::RegTensor<T> rhsReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;

    for (uint32_t i = 0; i < repeats; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(remaining);
        AscendC::Reg::LoadAlign(lhsReg, lhs + i * elementsPerVector);
        AscendC::Reg::LoadAlign(rhsReg, rhs + i * elementsPerVector);
        AscendC::Reg::Add(dstReg, lhsReg, rhsReg, mask);
        AscendC::Reg::StoreAlign(dst + i * elementsPerVector, dstReg, mask);
    }
}
#endif

template <uint32_t TileLength>
__aicore__ inline void AddBody(AscendC::LocalMemAllocator<AscendC::Hardware::UB>& allocator,
                               __gm__ uint8_t* lhs, __gm__ uint8_t* rhs, __gm__ uint8_t* dst, uint32_t offset)
{
    AscendC::GlobalTensor<half> lhsGm;
    AscendC::GlobalTensor<half> rhsGm;
    AscendC::GlobalTensor<half> dstGm;
    lhsGm.SetGlobalBuffer(reinterpret_cast<__gm__ half*>(lhs) + offset, TileLength);
    rhsGm.SetGlobalBuffer(reinterpret_cast<__gm__ half*>(rhs) + offset, TileLength);
    dstGm.SetGlobalBuffer(reinterpret_cast<__gm__ half*>(dst) + offset, TileLength);

    auto lhsLocal = allocator.Alloc<half, TileLength>();
    auto rhsLocal = allocator.Alloc<half, TileLength>();
    auto dstLocal = allocator.Alloc<half, TileLength>();

    AscendC::DataCopy(lhsLocal, lhsGm, TileLength);
    AscendC::DataCopy(rhsLocal, rhsGm, TileLength);
    AscendC::SetFlag<AscendC::HardEvent::MTE2_V>(EVENT_ID0);
    AscendC::WaitFlag<AscendC::HardEvent::MTE2_V>(EVENT_ID0);

#if defined(__NPU_ARCH__) && (__NPU_ARCH__ == 3510)
    asc_vf_call<AddRegisters<half, TileLength>>(
        reinterpret_cast<__ubuf__ half*>(dstLocal.GetPhyAddr()),
        reinterpret_cast<__ubuf__ half*>(lhsLocal.GetPhyAddr()),
        reinterpret_cast<__ubuf__ half*>(rhsLocal.GetPhyAddr()));
#else
    // dav-2201 is MemBase: its public vector API operates directly on UB tensors.
    AscendC::Add(dstLocal, lhsLocal, rhsLocal, TileLength);
#endif

    AscendC::SetFlag<AscendC::HardEvent::V_MTE3>(EVENT_ID0);
    AscendC::WaitFlag<AscendC::HardEvent::V_MTE3>(EVENT_ID0);
    AscendC::DataCopy(dstGm, dstLocal, TileLength);
    AscendC::PipeBarrier<PIPE_ALL>();
}

template <uint32_t TileLength>
__global__ __vector__ void AddKernel(__gm__ uint8_t* lhs, __gm__ uint8_t* rhs, __gm__ uint8_t* dst)
{
    AscendC::InitSocState();
    AscendC::LocalMemAllocator<AscendC::Hardware::UB> allocator;
    AddBody<TileLength>(allocator, lhs, rhs, dst, AscendC::GetBlockIdx() * TileLength);
}

template <uint32_t M, uint32_t K, uint32_t N, uint32_t SingleCoreM, uint32_t BaseM, uint32_t BaseK,
          uint32_t BaseN>
__aicore__ inline void MmadBody(__gm__ uint8_t* a, __gm__ uint8_t* b, __gm__ uint8_t* c)
{
    const uint32_t mTile = AscendC::GetBlockIdx() % (M / SingleCoreM);
    AscendC::GlobalTensor<half> aGm;
    AscendC::GlobalTensor<half> bGm;
    AscendC::GlobalTensor<half> cGm;
    aGm.SetGlobalBuffer(reinterpret_cast<__gm__ half*>(a) + mTile * SingleCoreM * K);
    bGm.SetGlobalBuffer(reinterpret_cast<__gm__ half*>(b));
    cGm.SetGlobalBuffer(reinterpret_cast<__gm__ half*>(c) + mTile * SingleCoreM * N);

    AscendC::LocalMemAllocator<AscendC::Hardware::L1> l1Allocator;
    AscendC::LocalMemAllocator<AscendC::Hardware::L0A> l0aAllocator;
    AscendC::LocalMemAllocator<AscendC::Hardware::L0B> l0bAllocator;
    AscendC::LocalMemAllocator<AscendC::Hardware::L0C> l0cAllocator;
    auto aL1 = l1Allocator.Alloc<AscendC::TPosition::A1, half>(BaseM * BaseK);
    auto bL1 = l1Allocator.Alloc<AscendC::TPosition::B1, half>(BaseK * BaseN);
    auto aL0 = l0aAllocator.Alloc<AscendC::TPosition::A2, half>(BaseM * BaseK);
    auto bL0 = l0bAllocator.Alloc<AscendC::TPosition::B2, half>(BaseK * BaseN);
    auto cL0 = l0cAllocator.Alloc<AscendC::TPosition::CO1, float>(BaseM * BaseN);

    AscendC::DataCopy(aL1, aGm, AscendC::Nd2NzParams{1, BaseM, BaseK, 0, K, BaseM, 1, 0});
    AscendC::DataCopy(bL1, bGm, AscendC::Nd2NzParams{1, BaseK, BaseN, 0, N, BaseK, 1, 0});
    AscendC::SetFlag<AscendC::HardEvent::MTE2_MTE1>(EVENT_ID0);
    AscendC::WaitFlag<AscendC::HardEvent::MTE2_MTE1>(EVENT_ID0);

#if defined(__NPU_ARCH__) && (__NPU_ARCH__ == 2201)
    // dav-2201: L1 NZ -> L0A ZZ and L0B ZN.
    for (uint32_t i = 0; i < BaseM / kCubeBlock; ++i) {
        AscendC::LoadData(
            aL0[i * BaseK * kCubeBlock], aL1[i * 512 / sizeof(half)],
            AscendC::LoadData2DParams{0, BaseK / kCubeBlock, BaseM / kCubeBlock, 0, 0, false, 0});
    }
    for (uint32_t i = 0; i < BaseK / kCubeBlock; ++i) {
        AscendC::LoadData(
            bL0[i * BaseN * kCubeBlock], bL1[i * 512 / sizeof(half)],
            AscendC::LoadData2DParams{0, BaseN / kCubeBlock, BaseK / kCubeBlock, 0, 0, true, 0});
    }
#elif defined(__NPU_ARCH__) && (__NPU_ARCH__ == 3510)
    // dav-3510: L1 NZ -> L0A NZ and L0B ZN.
    AscendC::LoadData(
        aL0, aL1,
        AscendC::LoadData2DParamsV2{
            0, 0, BaseM / kCubeBlock, BaseK / kCubeBlock, BaseM / kCubeBlock, BaseM / kCubeBlock, false, 0});
    AscendC::LoadData(
        bL0, bL1,
        AscendC::LoadData2DParamsV2{
            0, 0, BaseK / kCubeBlock, BaseN / kCubeBlock, BaseK / kCubeBlock, BaseN / kCubeBlock, true, 0});
#endif

    AscendC::SetFlag<AscendC::HardEvent::MTE1_M>(EVENT_ID0);
    AscendC::WaitFlag<AscendC::HardEvent::MTE1_M>(EVENT_ID0);
    AscendC::Mmad(cL0, aL0, bL0, AscendC::MmadParams{BaseM, BaseN, BaseK, 0, false, true});
    AscendC::SetFlag<AscendC::HardEvent::M_FIX>(EVENT_ID0);
    AscendC::WaitFlag<AscendC::HardEvent::M_FIX>(EVENT_ID0);
    AscendC::Fixpipe(
        cGm, cL0,
        AscendC::FixpipeParamsV220{BaseN, BaseM, BaseM, N, false, QuantMode_t::F322F16, 0, 1, 0, 0, 0});
    AscendC::PipeBarrier<PIPE_ALL>();
}

template <uint32_t M, uint32_t K, uint32_t N, uint32_t SingleCoreM, uint32_t BaseM, uint32_t BaseK,
          uint32_t BaseN>
__global__ __cube__ void MmadKernel(__gm__ uint8_t* a, __gm__ uint8_t* b, __gm__ uint8_t* c)
{
    AscendC::InitSocState();
    MmadBody<M, K, N, SingleCoreM, BaseM, BaseK, BaseN>(a, b, c);
}

template <uint32_t M, uint32_t K, uint32_t N, uint32_t SingleCoreM, uint32_t BaseM, uint32_t BaseK,
          uint32_t BaseN>
__global__ __mix__(1, 2) void AddMmadAddKernel(__gm__ uint8_t* a0, __gm__ uint8_t* a1, __gm__ uint8_t* b,
                                              __gm__ uint8_t* addend, __gm__ uint8_t* aStaging,
                                              __gm__ uint8_t* mmStaging, __gm__ uint8_t* output)
{
    AscendC::InitSocState();
    constexpr uint32_t preAddPerVectorCore = SingleCoreM * K / 2;
    constexpr uint32_t postAddPerVectorCore = SingleCoreM * N / 2;
    constexpr uint32_t aivToAic = 0;
    constexpr uint32_t aicToAiv = 1;

    if ASCEND_IS_AIV {
        AscendC::LocalMemAllocator<AscendC::Hardware::UB> allocator;
        const uint32_t preOffset = AscendC::GetBlockIdx() * preAddPerVectorCore;
        AddBody<preAddPerVectorCore>(allocator, a0, a1, aStaging, preOffset);
        // Both AIVs in the logical AI Core must arrive before its AIC reads staged A.
        AscendC::CrossCoreSetFlag<0x2, PIPE_MTE3>(aivToAic);
        AscendC::CrossCoreWaitFlag<0x2>(aicToAiv);
        const uint32_t postOffset = AscendC::GetBlockIdx() * postAddPerVectorCore;
        AddBody<postAddPerVectorCore>(allocator, mmStaging, addend, output, postOffset);
    }

    if ASCEND_IS_AIC {
        AscendC::CrossCoreWaitFlag<0x2>(aivToAic);
        MmadBody<M, K, N, SingleCoreM, BaseM, BaseK, BaseN>(aStaging, b, mmStaging);
        AscendC::CrossCoreSetFlag<0x2, PIPE_FIX>(aicToAiv);
    }
    AscendC::PipeBarrier<PIPE_ALL>();
}

}  // namespace lab
