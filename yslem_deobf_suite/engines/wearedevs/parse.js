const lp=require('./luaparse.js');const fs=require('fs');
const src=fs.readFileSync(process.argv[2],'latin1');
const ast=lp.parse(src,{luaVersion:'5.1',comments:false,scope:false,locations:false,ranges:false,encodingMode:'x-user-defined'});
fs.writeFileSync(process.argv[3],JSON.stringify(ast));
