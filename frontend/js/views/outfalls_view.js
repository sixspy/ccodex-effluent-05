export const outfallsViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>排放口限值</h3>
      <table>
        <thead><tr><th>编码</th><th>厂</th><th>河段</th><th>COD</th><th>氨氮</th><th>总磷</th><th>状态</th><th>正式批</th></tr></thead>
        <tbody>
          <tr v-for="o in outfalls" :key="o.id">
            <td>{{ o.outfall_code }}</td><td>{{ o.plant_code }}</td><td>{{ o.river_reach }}</td>
            <td>{{ o.cod_limit }}</td><td>{{ o.nh3n_limit }}</td><td>{{ o.tp_limit }}</td>
            <td :class="statusClass(o.status)">{{ o.status }}</td>
            <td><button class="secondary" @click="loadOutfallFormal(o)">正式批列表</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>新建排放口</h3>
      <div class="form-row"><div><label>编码</label><input v-model="outfallForm.outfall_code"/></div>
      <div><label>处理厂 ID</label><input type="number" v-model.number="outfallForm.plant_id"/></div></div>
      <label>河段</label><input v-model="outfallForm.river_reach"/>
      <div class="form-row">
        <div><label>COD 限</label><input type="number" v-model.number="outfallForm.cod_limit"/></div>
        <div><label>氨氮限</label><input type="number" v-model.number="outfallForm.nh3n_limit"/></div>
      </div>
      <label>总磷限</label><input type="number" v-model.number="outfallForm.tp_limit"/>
      <div class="actions"><button @click="createOutfall">登记</button></div>
    </div>
    <div class="panel" style="grid-column:1 / -1" v-if="outfallFormal">
      <h3>正式批列表 · {{ outfallFormalOf }}（不含无许可号）</h3>
      <p class="muted">{{ outfallFormal.rule }}</p>
      <table>
        <thead><tr><th>采样号</th><th>许可号</th><th>流量</th><th>状态</th><th>代</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="s in outfallFormal.items" :key="s.sample_code">
            <td>{{ s.sample_code }}</td><td>{{ s.permit_ref }}</td><td>{{ s.flow_m3h }}</td>
            <td :class="sampleClass(s.status)">{{ s.status }}</td><td>{{ s.generation }}</td><td>{{ s.created_at }}</td>
          </tr>
          <tr v-if="!outfallFormal.items.length"><td colspan="6" class="muted">该口暂无有许可匹配的正式批。</td></tr>
        </tbody>
      </table>
    </div>
  </div>`;
