/**
 * 家庭工作台 · 客户端插件
 *
 * 注册两处（与个人工作台同一套 API，见 dsh-personal-workstation/client/client.js）：
 *   1) 侧边栏一项「家庭工作台」（order 12，排在工作台后面）
 *   2) 主区域：iframe 指向本机家庭工作台 http://127.0.0.1:8300/
 *
 * 为什么用 iframe：家庭工作台是本机独立服务（只绑 127.0.0.1，tailnet 侧走 tailscale serve），
 * 用 iframe 嵌进来不需要把两边的构建链耦合在一起；出问题也只影响这一块。
 */
window.__ModuleLoader__.load({id:'dsh-family-workbench', factory:(require)=>{
  const React=require('react');
  const h=React.createElement;
  const PAGE_TITLE='家庭工作台';
  const WORKBENCH_URL='http://127.0.0.1:8300/';

  function frame(src,title){
    return h('iframe',{src,title,style:{width:'100%',height:'100%',minHeight:0,flex:1,border:0,display:'block'},allow:'fullscreen'});
  }
  // 房子图标（与家庭工作台 VI 一致：线宽 1.6、圆角）
  function Icon({size=20}={}){
    return h('svg',{width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.6,'aria-hidden':true},
      h('path',{d:'M4 11.5 12 4l8 7.5'}),
      h('path',{d:'M6.5 10.5V20h11v-9.5'}),
      h('path',{d:'M10 20v-5h4v5'}));
  }
  return {name:'dsh-family-workbench',inject:['slots'],apply(ctx){
    ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:'family-workbench'},()=>frame(WORKBENCH_URL,PAGE_TITLE)));
    ctx.slots.inject('sidebar.panellist',()=>ctx.slots.register({name:'sidebar.panellist',id:'family-workbench',label:PAGE_TITLE,order:12},Icon));
  }};
}});
