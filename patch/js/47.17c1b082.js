"use strict";(self["webpackChunkapp"]=self["webpackChunkapp"]||[]).push([[47],{5765:function(e,t,o){o.d(t,{A:function(){return v}});var n=o(6768),i=o(4232),a=o(5130);const s={class:"copy-button-main"},c={class:"material-icons"},r={key:0,class:"copy"};function l(e,t,o,l,d,u){return(0,n.uX)(),(0,n.CE)("div",s,[(0,n.Lk)("button",{onClick:t[0]||(t[0]=(...e)=>u.copy&&u.copy(...e))},[(0,n.Lk)("i",c,(0,i.v_)(o.icon),1),o.buttonText?((0,n.uX)(),(0,n.CE)("div",r,(0,i.v_)(o.buttonText),1)):(0,n.Q3)("",!0)]),(0,n.bF)(a.eB,{name:"fade"},{default:(0,n.k6)((()=>[d.displayNotification?((0,n.uX)(),(0,n.CE)("div",{key:0,id:"copy-notification",style:(0,i.Tr)(d.notificationStyle)},"Copied to clipboard!",4)):(0,n.Q3)("",!0)])),_:1})])}var d={name:"CopyButton",props:{textToCopy:String,icon:{type:String,default:"content_copy"},buttonText:{type:String,default:""}},data(){return{displayNotification:!1,notificationStyle:{top:0,left:0}}},methods:{copy(e){const{clientX:t,clientY:o}=e;this.notificationStyle={top:`${o}px`,left:`${t}px`},navigator.clipboard.writeText(this.textToCopy).then((()=>{this.displayNotification=!0,setTimeout((()=>{this.displayNotification=!1}),1500)}))}}},u=o(1241);const p=(0,u.A)(d,[["render",l],["__scopeId","data-v-08b220a4"]]);var v=p},9554:function(e,t,o){o.d(t,{A:function(){return h}});var n=o(6768),i=o(5130),a=o(4232);const s={class:"download-results-main"},c={class:"download-body"},r={class:"options"},l={class:"download"};function d(e,t,o,d,u,p){const v=(0,n.g2)("floating-modal");return(0,n.uX)(),(0,n.CE)("div",s,[o.showDownloadResults?((0,n.uX)(),(0,n.Wv)(v,{key:0,title:"DownloadResults",onCloseModal:t[2]||(t[2]=t=>e.$emit("hideDownloadResults"))},{default:(0,n.k6)((()=>[(0,n.Lk)("div",c,[t[5]||(t[5]=(0,n.Lk)("div",{class:"title"},"Select your desired file type and then click download.",-1)),(0,n.Lk)("div",r,[t[4]||(t[4]=(0,n.Lk)("label",{for:"file-type-select"},"File type:",-1)),(0,n.bo)((0,n.Lk)("select",{id:"file-type-select","onUpdate:modelValue":t[0]||(t[0]=e=>u.fileType=e)},t[3]||(t[3]=[(0,n.Lk)("option",{value:"pb.gz"},"pb.gz",-1),(0,n.Lk)("option",{value:"csv",disabled:""},"csv (coming soon)",-1),(0,n.Lk)("option",{value:"pbtxt",disabled:""},"pbtxt (coming soon)",-1)]),512),[[i.u1,u.fileType]])]),(0,n.Lk)("div",l,[(0,n.Lk)("button",{onClick:t[1]||(t[1]=(...e)=>p.downloadResults&&p.downloadResults(...e))},"Download "+(0,a.v_)(u.fileType)+" file",1)])])])),_:1})):(0,n.Q3)("",!0)])}o(4603),o(7566),o(8721);var u=o(2272),p={name:"DownloadResults",props:{reactionIds:Array,showDownloadResults:Boolean},components:{"floating-modal":u.A},watch:{fileType(e){this.$store.commit("setDownloadFileType",e)}},data(){return{fileType:"pb.gz"}},methods:{downloadResults(){const e=new XMLHttpRequest;e.open("POST","/api/download_results"),e.responseType="blob",e.onload=()=>{if(200===e.status){const t=URL.createObjectURL(e.response),o=document.createElement("a");o.href=t,o.download="ord_search_results.pb.gz",o.click(),setTimeout((()=>{URL.revokeObjectURL(t),o.remove()}),100)}},e.setRequestHeader("Content-Type","application/json");const t=this.reactionIds.map((e=>({"Reaction ID":e})));e.send(JSON.stringify(t))}},mounted(){this.fileType=this.$store.state.downloadFileType||"pb.gz"}},v=o(1241);const f=(0,v.A)(p,[["render",d],["__scopeId","data-v-93fb3834"]]);var h=f},1851:function(e,t,o){o.d(t,{A:function(){return U}});var n=o(6768),i=o(4232);const a={class:"reaction-container"},s={key:0,class:"select"},c=["id","value","checked"],r=["for"],l=["innerHTML"],d={class:"info"},u={class:"col full"},p={class:"col"},v={class:"yield"},f={class:"conversion"},h={class:"conditions"},y={key:0,class:"smile"},k={class:"value"},m={class:"col"},L={class:"creator"},b={class:"date"},g={class:"doi"},w={class:"publication"},T=["href"],C={class:"dataset"};function _(e,t,o,_,S,R){const A=(0,n.g2)("LoadingSpinner"),x=(0,n.g2)("router-link"),D=(0,n.g2)("CopyButton");return(0,n.uX)(),(0,n.CE)("div",a,[(0,n.Lk)("div",{class:(0,i.C4)(["row",o.isSelected?"selected":""])},[o.isSelectable?((0,n.uX)(),(0,n.CE)("div",s,[(0,n.Lk)("input",{type:"checkbox",id:"select_"+o.reaction.reaction_id,value:o.reaction.reaction_id,checked:o.isSelected,onChange:t[0]||(t[0]=t=>e.$emit("clickedSelect",t))},null,40,c),(0,n.Lk)("label",{for:"select_"+o.reaction.reaction_id},"Select reaction",8,r)])):(0,n.Q3)("",!0),S.reactionTable?((0,n.uX)(),(0,n.CE)("div",{key:1,class:"reaction-table",innerHTML:S.reactionTable},null,8,l)):((0,n.uX)(),(0,n.Wv)(A,{key:2})),(0,n.Lk)("div",d,[(0,n.Lk)("div",u,[(0,n.bF)(x,{to:{name:"reaction-view",params:{reactionId:o.reaction.reaction_id}}},{default:(0,n.k6)((()=>t[1]||(t[1]=[(0,n.Lk)("button",null,"View Full Details",-1)]))),_:1},8,["to"])]),(0,n.Lk)("div",p,[(0,n.Lk)("div",v,"Yield: "+(0,i.v_)(R.getYield(o.reaction.data.outcomesList[0].productsList[0].measurementsList)),1),(0,n.Lk)("div",f,"Conversion: "+(0,i.v_)(R.getConversion(o.reaction.data)),1),(0,n.Lk)("div",h,"Conditions: "+(0,i.v_)(R.conditionsAndDuration(o.reaction.data).join("; ")||"Not Listed"),1),o.reaction.data.outcomesList[0].productsList[0].identifiersList.length?((0,n.uX)(),(0,n.CE)("div",y,[(0,n.bF)(D,{textToCopy:o.reaction.data.outcomesList[0].productsList[0].identifiersList[0].value},null,8,["textToCopy"]),(0,n.Lk)("div",k,"Product "+(0,i.v_)(R.productIdentifier(o.reaction.data.outcomesList[0].productsList[0].identifiersList[0])),1)])):(0,n.Q3)("",!0)]),(0,n.Lk)("div",m,[(0,n.Lk)("div",L,"Uploaded by "+(0,i.v_)(o.reaction.data.provenance.recordCreated.person.name)+", "+(0,i.v_)(o.reaction.data.provenance.recordCreated.person.organization),1),(0,n.Lk)("div",b,"Uploaded on "+(0,i.v_)(new Date(o.reaction.data.provenance.recordCreated.time.value).toLocaleDateString()),1),(0,n.Lk)("div",g,"DOI: "+(0,i.v_)(o.reaction.data.provenance.doi),1),(0,n.Lk)("div",w,[(0,n.Lk)("a",{href:o.reaction.data.provenance.publicationUrl,target:"_blank"},"Publication URL",8,T)]),(0,n.Lk)("div",C,"Dataset: "+(0,i.v_)(o.reaction.dataset_id),1)])])],2)])}o(4114);var S=o(6466),R=o(5839),A=o(7547),x=o(9518),D=o.n(x),$=o(5765),N={props:{reaction:Object,isSelected:Boolean,isSelectable:Boolean},components:{LoadingSpinner:S.A,CopyButton:$.A},data(){return{formattedResults:[],selectedReactions:[],reactionTable:null}},methods:{getReactionTable(){fetch(`/api/render/${this.reaction.reaction_id}`).then((e=>e.json())).then((e=>{this.reactionTable=e}))},getYield(e){const t=e.find((e=>3==e.type));return t?.percentage?`${t.percentage.value}%`:"Not listed"},getConversion(e){if(!e.outcomesList[0].conversion)return"Not listed"},conditionsAndDuration(e){const t=[],o=R.A.tempSetPoint(e.conditions.temperature?.setpoint);"None"!==o&&t.push(`at ${o}`);const n=R.A.pressureSetPoint(e.conditions.pressure?.setpoint);"None"!==n&&t.push(`under ${n}`);const i=A.A.formattedTime(e.outcomesList[0]?.reactionTime);i&&"None"!==i&&void 0!==i&&t.push(`for ${i}`);const a=R.A.stirType(e.conditions.stirring?.type);a&&"None"!==a&&void 0!==a&&t.push(`under ${a}`);const s=R.A.mechType(e.conditions.mechanochemistry?.type);return s&&"None"!==s&&void 0!==s&&t.push(`with ${s}`),t},productIdentifier(e){const t=D().CompoundIdentifier.CompoundIdentifierType,o=Object.keys(t).find((o=>t[o]==e.type));return`${o}: ${e.value}`},updateSelectedReactions(e){if(e.target.checked)this.selectedReactions.push(e.target.value);else{let t=this.selectedReactions.indexOf(e.target.value);-1!==t&&this.selectedReactions.splice(t,1)}}},async mounted(){this.getReactionTable()}},E=o(1241);const I=(0,E.A)(N,[["render",_],["__scopeId","data-v-7c202560"]]);var U=I},655:function(e,t,o){var n=o(6955),i=String;e.exports=function(e){if("Symbol"===n(e))throw new TypeError("Cannot convert a Symbol value to a string");return i(e)}},2812:function(e){var t=TypeError;e.exports=function(e,o){if(e<o)throw new t("Not enough arguments");return e}},4603:function(e,t,o){var n=o(6840),i=o(9504),a=o(655),s=o(2812),c=URLSearchParams,r=c.prototype,l=i(r.append),d=i(r["delete"]),u=i(r.forEach),p=i([].push),v=new c("a=1&a=2&b=3");v["delete"]("a",1),v["delete"]("b",void 0),v+""!=="a=2"&&n(r,"delete",(function(e){var t=arguments.length,o=t<2?void 0:arguments[1];if(t&&void 0===o)return d(this,e);var n=[];u(this,(function(e,t){p(n,{key:t,value:e})})),s(t,1);var i,c=a(e),r=a(o),v=0,f=0,h=!1,y=n.length;while(v<y)i=n[v++],h||i.key===c?(h=!0,d(this,i.key)):f++;while(f<y)i=n[f++],i.key===c&&i.value===r||l(this,i.key,i.value)}),{enumerable:!0,unsafe:!0})},7566:function(e,t,o){var n=o(6840),i=o(9504),a=o(655),s=o(2812),c=URLSearchParams,r=c.prototype,l=i(r.getAll),d=i(r.has),u=new c("a=1");!u.has("a",2)&&u.has("a",void 0)||n(r,"has",(function(e){var t=arguments.length,o=t<2?void 0:arguments[1];if(t&&void 0===o)return d(this,e);var n=l(this,e);s(t,1);var i=a(o),c=0;while(c<n.length)if(n[c++]===i)return!0;return!1}),{enumerable:!0,unsafe:!0})},8721:function(e,t,o){var n=o(3724),i=o(9504),a=o(2106),s=URLSearchParams.prototype,c=i(s.forEach);n&&!("size"in s)&&a(s,"size",{get:function(){var e=0;return c(this,(function(){e++})),e},configurable:!0,enumerable:!0})}}]);
//# sourceMappingURL=47.17c1b082.js.map