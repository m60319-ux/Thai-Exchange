// Smoke-test the rendered website with a simulated browser.
// This exercises actual inline scripts, not merely JavaScript parse checks.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { JSDOM, VirtualConsole } = require('jsdom');
const html = fs.readFileSync('index.html','utf8');
const actual = JSON.parse(fs.readFileSync('rates.json','utf8'));
const now = new Date().toISOString();

function sampleData(officialAvailable, referenceAvailable) {
  const clone = JSON.parse(JSON.stringify(actual));
  clone.schema_version = 2;
  clone.checked_at = now;
  delete clone.official.bot;
  delete clone.reference.bot;
  const cash={USD:32.73,EUR:36.74,JPY:.2096,CNY:4.915};
  const source='https://www.cathaybk.com.tw/';
  const bank={
    status:'ok',source,quoted_at:now,
    bank_name:'國泰世華 → 台新（依幣別回退）',
    cash_sell:cash,unsupported:['KRW'],
    currency_sources:Object.fromEntries(
      ['USD','EUR','JPY','CNY'].map(code=>[
        code,{bank:'cathay',bank_name:'國泰世華銀行',source,quoted_at:now}
      ])
    )
  };
  clone.official.cathay={
    status:'ok',source,quoted_at:now,bank_name:'國泰世華銀行',
    cash_sell:cash,unsupported:['KRW']
  };
  clone.official.taishin={
    status:'ok',source:'https://my.taishinbank.com.tw/',quoted_at:now,
    bank_name:'台新銀行',cash_sell:{USD:32.70,EUR:36.70,JPY:.2096,CNY:4.91},
    unsupported:['KRW']
  };
  clone.official.bank=(officialAvailable||referenceAvailable)
    ? JSON.parse(JSON.stringify(bank))
    : {status:'failed',error:'沒有可用的銀行現鈔賣出價'};
  clone.official.grand_superrich=officialAvailable?{
    status:'ok',source:'https://www.grandsuperrich.com/rate.php',quoted_at:now,
    cash_buy:{TWD:1.03,USD:33.7,EUR:37.6,JPY:.213,KRW:.0255,CNY:5.04},
    denomination_labels:{TWD:'TWD',USD:'USD 100',EUR:'EUR 500-100',
      JPY:'JPY 10000-5000',KRW:'KRW 非小面額',CNY:'CNY 100'}
  }:{status:'failed',error:'Grand SuperRich 官網無法讀取'};
  clone.reference.bank=referenceAvailable
    ? JSON.parse(JSON.stringify(bank))
    : {status:'failed',error:'參考銀行資料不足'};
  clone.reference.grand_superrich=referenceAvailable?{
    status:'ok',quoted_at:now,
    source:'https://exchange.ruamthai.com/en/shop/grand-superrich',
    cash_buy:{TWD:1.03,USD:33.65,EUR:37.5,JPY:.213,KRW:.0255,CNY:5.04},
    denomination_labels:{TWD:'TWD',USD:'USD 100',EUR:'EUR 500-100',
      JPY:'JPY 10000-5000',KRW:'KRW 非小面額',CNY:'CNY 100'}
  }:{status:'failed',error:'RuamThai 資料不足'};
  return clone;
}

function marketRows() {
  const d = ['2026-10-23','2026-10-26','2026-10-27'];
  const names = {THB:1.04,USD:.033,EUR:.027,JPY:4.8,KRW:43,CNY:.23};
  return d.flatMap((date,i)=>Object.entries(names).map(([quote,rate])=>({
    date,base:'TWD',quote,rate:rate*(1+i*.002)
  })));
}
const tick=()=>new Promise(resolve=>setTimeout(resolve,80));
async function runCase(label,officialAvailable,referenceAvailable){
  const errors=[];
  const console = new VirtualConsole();
  console.on('jsdomError',e=>errors.push(e.message));
  console.on('error',e=>errors.push(e));
  const data = sampleData(officialAvailable,referenceAvailable);
  const dom = new JSDOM(html,{
    url:'https://m60319-ux.github.io/Thai-Exchange/',
    runScripts:'dangerously',
    pretendToBeVisual:true,
    virtualConsole:console,
    beforeParse(window){
      window.fetch=async path=>({
        ok:true,status:200,
        json:async()=>String(path).includes('rates.json')?data:marketRows()
      });
      window.scrollTo=()=>{};
    }
  });
  await tick();
  const d=dom.window.document;
  const get=selector=>d.querySelector(selector);
  assert.deepEqual(errors,[],label+': no runtime exceptions');
  assert.ok(get('#officialCards').textContent.includes(officialAvailable?'官方直接取得':'官方取得失敗'),label+': official status card');
  assert.ok(get('#referenceCards').textContent.includes(referenceAvailable?'第三方參考可用':'參考來源失敗'),label+': mirror status card');
  assert.ok(get('#chartOutput svg'),label+': historical FX chart renders');
  if(officialAvailable){
    assert.equal(get('#officialToggle').getAttribute('aria-pressed'),'true',label+': official selected');
    assert.ok(get('#bars').textContent.includes('美元'),label+': official ranking present');
    assert.ok(get('#primaryRankingSource').textContent.includes('官方直接取得'),label+': official provenance label');
    get('#referenceToggle').click();
    assert.ok(get('#primaryRankingSource').textContent.includes('第三方參考'),label+': reference switch');
  }else if(referenceAvailable){
    assert.equal(get('#referenceToggle').getAttribute('aria-pressed'),'true',label+': reference auto-selected');
    assert.ok(get('#bars').textContent.includes('台幣直接換'),label+': reference ranking populated');
    assert.ok(get('#bars').textContent.includes('美元'),label+': six routes calculated');
    assert.ok(get('#primaryRankingSource').textContent.includes('第三方參考'),label+': no masquerading as official');
    get('#officialToggle').click();
    assert.equal(get('#bestName').textContent,'官方資料不足',label+': official ranking disabled');
    assert.ok(get('#bars').textContent.includes('官方取得失敗'),label+': explicit official failure');
    get('#referenceToggle').click();
    assert.ok(get('#bars').textContent.includes('美元'),label+': reference restored');
  }else{
    assert.equal(get('#bestName').textContent,'官方資料不足',label+': no fake ranking');
    assert.equal(get('#referenceToggle').getAttribute('aria-pressed'),'false');
  }
  get('#manualToggle').click();
  assert.ok(d.querySelectorAll('#rateBody input').length>=10,label+': editable manual quote inputs');
  assert.ok(get('#primaryRankingSource').textContent.includes('手動設定'),label+': manual provenance');
  get('#amount').value='200000';
  get('#amount').dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  assert.ok(get('#bestAmount').textContent.includes('205,000'),label+': amount recalculates from manual rates');
  get('#historyPeriods [data-days="7"]').click();
  await tick();
  assert.ok(get('#chartOutput svg'),label+': 7-day chart still renders');
  assert.deepEqual(errors,[],label+': no runtime errors during interactions');
  dom.window.close();
  process.stdout.write('PASS: '+label+'\n');
}
(async()=>{
  await runCase('Grand official blocked; labeled reference comparison',false,true);
  await runCase('Official success; official comparison',true,true);
  await runCase('Both data sources failed; manual still works',false,false);
  await runBankFallbackCase();

async function runBankFallbackCase(){
  const data=sampleData(true,false);
  data.official.cathay={
    status:'ok',source:'https://www.cathaybk.com.tw/',quoted_at:now,
    cash_sell:{USD:32.73,EUR:36.74,JPY:.2096,CNY:4.915},
    unsupported:['KRW']
  };
  data.official.taishin={
    status:'ok',source:'https://my.taishinbank.com.tw/',quoted_at:now,
    cash_sell:{USD:32.69,EUR:36.70,JPY:.2095,CNY:4.91},
    unsupported:['KRW']
  };
  data.official.bank={
    status:'ok',source:data.official.cathay.source,quoted_at:now,
    bank_name:'國泰世華 → 台新（依幣別回退）',
    cash_sell:data.official.cathay.cash_sell,
    currency_sources:Object.fromEntries(
      ['USD','EUR','JPY','CNY'].map(code=>[
        code,{bank:'cathay',bank_name:'國泰世華銀行',
              source:data.official.cathay.source,quoted_at:now}
      ])
    ),
    unsupported:['KRW']
  };
  data.official.bank.cash_sell.CNY=4.91;
  data.official.bank.currency_sources.CNY={bank:'taishin',bank_name:'台新銀行',
    source:data.official.taishin.source,quoted_at:now};
  const errs=[],vc=new VirtualConsole();
  vc.on('jsdomError',e=>errs.push(e.message));
  const dom=new JSDOM(html,{
    url:'https://m60319-ux.github.io/Thai-Exchange/',
    runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc,
    beforeParse(win){
      win.fetch=async path=>({
        ok:true,status:200,
        json:async()=>String(path).includes('rates.json')?data:marketRows()
      });
      win.scrollTo=()=>{};
    }
  });
  await tick();
  const d=dom.window.document;
  assert.deepEqual(errs,[],'fallback no JS errors');
  assert.equal(d.querySelector('#officialToggle').getAttribute('aria-pressed'),'true');
  assert.ok(d.querySelector('#bars').textContent.includes('國泰世華銀行'));
  assert.ok(d.querySelector('#primaryRankingSource').textContent.includes('國泰世華銀行'));
  assert.ok(d.querySelector('#rateBody').textContent.includes('台新銀行'));
  assert.ok(!html.includes('FindRate'));
  assert.ok(!html.includes('rate.bot.com.tw'));
  assert.ok(d.querySelector('#officialCards').textContent.includes('台新銀行'));
  assert.ok(d.querySelector('#rateBody').textContent.includes('未提供現鈔賣出'));
  assert.ok(d.querySelector('#bars').textContent.includes('KRW'));
  assert.ok(!d.body.textContent.includes('台銀'), 'removed bank should not appear');
  assert.equal(d.querySelectorAll('#bars .bar-row').length,5,
               'TWD plus four actual currency banknote offers; never fake KRW');
  assert.ok(!d.querySelector('#bars').textContent.includes('NaN'));
  assert.ok(!d.querySelector('#bars').textContent.includes('Infinity'));
  assert.ok(d.querySelector('#chartOutput svg'));
  dom.window.close();
  process.stdout.write('PASS: Cathay primary, Taishin secondary, KRW unavailable\n');
}
})().catch(e=>{console.error(e);process.exit(1);});
