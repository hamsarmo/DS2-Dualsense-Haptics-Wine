/* SPDX-License-Identifier: MIT
 * Query Sony's identity and Windows endpoints. No audio buffers or HID output.
 */
#define COBJMACROS
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <initguid.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <devpkey.h>
#include <setupapi.h>
#include <hidsdi.h>

static int wired_count(void) {
 GUID guid; HidD_GetHidGuid(&guid);
 HDEVINFO ds=SetupDiGetClassDevsW(&guid,NULL,NULL,DIGCF_PRESENT|DIGCF_DEVICEINTERFACE);
 if(ds==INVALID_HANDLE_VALUE)return -1;
 unsigned count=0;
 for(DWORD i=0;;i++) {
  SP_DEVICE_INTERFACE_DATA di={.cbSize=sizeof(di)};
  if(!SetupDiEnumDeviceInterfaces(ds,NULL,&guid,i,&di))break;
  DWORD size=0;SetupDiGetDeviceInterfaceDetailW(ds,&di,NULL,0,&size,NULL);
  if(!size)continue;
  SP_DEVICE_INTERFACE_DETAIL_DATA_W *d=malloc(size);if(!d)continue;
  d->cbSize=sizeof(*d);
  if(SetupDiGetDeviceInterfaceDetailW(ds,&di,d,size,NULL,NULL)) {
   HANDLE h=CreateFileW(d->DevicePath,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,0,NULL);
   HIDD_ATTRIBUTES a={.Size=sizeof(a)};PHIDP_PREPARSED_DATA p=NULL;HIDP_CAPS caps;
   if(h!=INVALID_HANDLE_VALUE) {
    if(HidD_GetAttributes(h,&a)&&a.VendorID==0x054c&&a.ProductID==0x0ce6&&HidD_GetPreparsedData(h,&p)) {
     if(HidP_GetCaps(p,&caps)==HIDP_STATUS_SUCCESS&&caps.UsagePage==1&&caps.Usage==5&&caps.InputReportByteLength==64)count++;
     HidD_FreePreparsedData(p);
    }
    CloseHandle(h);
   }
  }
  free(d);
 }
 SetupDiDestroyDeviceInfoList(ds);return count;
}
int wmain(int argc,wchar_t **argv) {
 if(argc!=2)return 2;
 int pads=wired_count();printf("WIRED_COUNT=%d\n",pads);if(pads!=1)return 3;
 if(wcscmp(argv[1],L"-")) {
  HMODULE m=LoadLibraryW(argv[1]);if(!m){printf("Sony load error=%lu\n",GetLastError());return 4;}
  int (*init)(void)=(void*)GetProcAddress(m,"scePadInit");
  int (*openpad)(int,int,int,void*)=(void*)GetProcAddress(m,"scePadOpen");
  int (*getid)(int,void*)=(void*)GetProcAddress(m,"scePadGetContainerIdInformation");
  int (*closepad)(int)=(void*)GetProcAddress(m,"scePadClose");
  void (*term)(void)=(void*)GetProcAddress(m,"scePadTerminate");
  if(!init||!openpad||!getid||!closepad||!term)return 5;
  if(init()<0)return 6;
  int h=openpad(1,0,0,NULL),r=-1;DWORD data[0x801]={0};
  if(h>0){Sleep(2000);r=getid(h,data);closepad(h);}
  term();
  if(r<0||data[0]!=78)return 7;
  GUID guid; if(FAILED(CLSIDFromString((wchar_t*)(data+1),&guid)))return 8;
  printf("SONY_ID=%ls\n",(wchar_t*)(data+1));
 }
 if(FAILED(CoInitializeEx(NULL,COINIT_MULTITHREADED)))return 9;
 IMMDeviceEnumerator *en=NULL;
 if(FAILED(CoCreateInstance(&CLSID_MMDeviceEnumerator,NULL,CLSCTX_ALL,&IID_IMMDeviceEnumerator,(void**)&en)))return 10;
 unsigned render_count=0;
 for(int flow=0;flow<=1;flow++) {
  IMMDeviceCollection *coll=NULL;UINT count=0;
  if(FAILED(IMMDeviceEnumerator_EnumAudioEndpoints(en,flow,DEVICE_STATE_ACTIVE,&coll)))continue;
  IMMDeviceCollection_GetCount(coll,&count);
  for(UINT i=0;i<count;i++) {
   IMMDevice *d=NULL;IPropertyStore *props=NULL;PROPVARIANT name,cid;LPWSTR id=NULL;
   PropVariantInit(&name);PropVariantInit(&cid);
   if(FAILED(IMMDeviceCollection_Item(coll,i,&d)))continue;
   if(SUCCEEDED(IMMDevice_OpenPropertyStore(d,STGM_READ,&props))) {
    IPropertyStore_GetValue(props,(const PROPERTYKEY*)&DEVPKEY_Device_FriendlyName,&name);
    if(name.vt==VT_LPWSTR&&(wcsstr(name.pwszVal,L"DualSense")||!wcscmp(name.pwszVal,L"Wireless Controller"))) {
     UINT channels=0;IAudioClient *client=NULL;WAVEFORMATEX *fmt=NULL;
     if(SUCCEEDED(IMMDevice_Activate(d,&IID_IAudioClient,CLSCTX_ALL,NULL,(void**)&client))) {
      if(SUCCEEDED(IAudioClient_GetMixFormat(client,&fmt)))channels=fmt->nChannels;
      CoTaskMemFree(fmt);IAudioClient_Release(client);
     }
     if(flow==1||channels==4) {
      if(SUCCEEDED(IMMDevice_GetId(d,&id))) {
       WCHAR value[40]=L"";IPropertyStore_GetValue(props,(const PROPERTYKEY*)&DEVPKEY_Device_ContainerId,&cid);
       if(cid.vt==VT_CLSID&&cid.puuid)StringFromGUID2(cid.puuid,value,40);
       printf("ENDPOINT=%s|%ls|%u|%ls\n",flow?"Capture":"Render",id,cid.vt,value);
       if(!flow)render_count++;
      }
     }
    }
    IPropertyStore_Release(props);
   }
   CoTaskMemFree(id);PropVariantClear(&name);PropVariantClear(&cid);IMMDevice_Release(d);
  }
  IMMDeviceCollection_Release(coll);
 }
 IMMDeviceEnumerator_Release(en);CoUninitialize();
 return render_count==1?0:11;
}
