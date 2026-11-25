export const reconcileViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>许可对账</h3>
      <div class="actions"><button class="secondary" @click="loadReconcile">刷新全部</button></div>
      <table>
        <thead><tr><th>许可</th><th>对齐</th><th>证明</th><th>封批数</th></tr></thead>
        <tbody>
          <tr v-for="r in reconAllItems" :key="r.permit_code">
            <td>{{ r.permit_code }}</td>
            <td :class="r.balanced?'pass':'fail'">{{ r.balanced ? "齐" : "不齐" }}</td>
            <td :class="r.proof_ready?'pass':'warn'">{{ r.proof_ready ? "可证" : "未齐" }}</td>
            <td>{{ r.seal_count || 0 }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>单许可 / 采样证明</h3>
      <label>许可号</label><input v-model="reconCode"/>
      <div class="actions"><button @click="loadReconcileOne">对账</button></div>
      <pre v-if="reconOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(reconOne, null, 2) }}</pre>
      <label>采样号证明</label><input v-model="proofCode"/>
      <div class="actions"><button class="secondary" @click="loadProof">证明</button></div>
      <pre v-if="proofOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(proofOne, null, 2) }}</pre>
    </div>
    <div class="panel" style="grid-column:1 / -1">
      <h3>流量累计口径 · 无许可批已剔除（effluent-05 乙）</h3>
      <div v-if="reconSummary" class="stats" style="margin:0.4rem 0">
        <div class="stat"><div class="n">{{ reconSummary.counted_flow_m3h }}</div><div class="l">累计流量 m3/h（仅有许可）</div></div>
        <div class="stat"><div class="n">{{ reconSummary.excluded_no_permit_flow_m3h }}</div><div class="l">剔除无许可流量</div></div>
        <div class="stat"><div class="n">{{ reconSummary.excluded_no_permit_count }}</div><div class="l">剔除无许可批数</div></div>
        <div class="stat"><div class="n">{{ reconSummary.counted_batch_count }}/{{ reconSummary.formal_batch_count }}</div><div class="l">计账正式批/总正式批</div></div>
      </div>
      <p v-if="reconSummary" class="muted">{{ reconSummary.rule }}</p>
      <table>
        <thead><tr><th>剔除采样号</th><th>无匹配许可号</th><th>排放口</th><th>流量</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="x in reconExcluded" :key="x.sample_code">
            <td>{{ x.sample_code }}</td><td class="fail">{{ x.permit_ref }}</td>
            <td>{{ x.outfall_code || "—" }}</td><td>{{ x.flow_m3h }}</td><td>{{ x.status }}</td>
          </tr>
          <tr v-if="!reconExcluded.length"><td colspan="5" class="muted">无无许可批，累计口径干净。</td></tr>
        </tbody>
      </table>
    </div>
  </div>`;
