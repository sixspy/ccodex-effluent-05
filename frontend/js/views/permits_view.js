export const permitsViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>排放许可册</h3>
      <table>
        <thead><tr><th>许可号</th><th>厂</th><th>配额</th><th>COD帽</th><th>期别</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="p in permits" :key="p.id">
            <td>{{ p.permit_code }}</td><td>{{ p.plant_code }}</td><td>{{ p.quota_m3d }}</td>
            <td>{{ p.cod_cap }}</td><td>{{ p.period_label }}</td>
            <td :class="statusClass(p.status)">{{ p.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>登记许可</h3>
      <div class="form-row"><div><label>许可号</label><input v-model="permitForm.permit_code"/></div>
      <div><label>厂 ID</label><input type="number" v-model.number="permitForm.plant_id"/></div></div>
      <div class="form-row"><div><label>配额</label><input type="number" v-model.number="permitForm.quota_m3d"/></div>
      <div><label>期别</label><input v-model="permitForm.period_label"/></div></div>
      <div class="form-row">
        <div><label>COD帽</label><input type="number" v-model.number="permitForm.cod_cap"/></div>
        <div><label>氨氮帽</label><input type="number" v-model.number="permitForm.nh3n_cap"/></div>
      </div>
      <label>总磷帽</label><input type="number" v-model.number="permitForm.tp_cap"/>
      <div class="actions"><button @click="createPermit">登记</button></div>
    </div>
    <div class="panel">
      <h3>许可号匹配核查（无许可禁建）</h3>
      <p class="muted">许可册查无此号时，采样页建批键拒写、对账剔除其流量、总览拦截加一。</p>
      <div class="form-row">
        <div><label>许可号</label><input v-model="permitCheckCode" placeholder="DP-E55"/></div>
      </div>
      <div class="actions"><button class="secondary" @click="checkPermit">核查匹配</button></div>
      <div v-if="permitCheckResult" style="margin-top:0.6rem">
        <p v-if="permitCheckResult.ok" class="pass">✔ 在册：{{ permitCheckResult.permit_code }} · {{ permitCheckResult.status }}</p>
        <p v-else class="fail">⛔ 许可册无匹配（{{ permitCheckResult.code }}）：无许可禁建，采样正式册零增并拒收。{{ permitCheckResult.message }}</p>
      </div>
    </div>
    <div class="panel" style="grid-column:1 / -1">
      <h3>无许可禁建 · 拦截痕（与总览计数/采样拒收同源）</h3>
      <table>
        <thead><tr><th>时间</th><th>许可号</th><th>归类</th><th>来源</th><th>操作会话</th></tr></thead>
        <tbody>
          <tr v-for="b in permitBlocks" :key="b.id">
            <td>{{ b.created_at }}</td><td>{{ b.permit_ref }}</td>
            <td :class="b.block_kind==='无许可禁建偏航' ? 'fail' : 'warn'">{{ b.block_kind }}</td>
            <td>{{ b.source }}</td><td>{{ b.actor }}</td>
          </tr>
          <tr v-if="!permitBlocks.length"><td colspan="5" class="muted">暂无拦截；到采样页用 DP-E55 建批即留痕并计数。</td></tr>
        </tbody>
      </table>
    </div>
  </div>`;
