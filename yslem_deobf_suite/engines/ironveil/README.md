# Ironveil V1 Deobfuscator

made by LeakD (discord.gg/qteAQmfJmP)

this is an open source deobfuscator for ironveil v1. i will update it every time ironveil gets updated.

also here is the original ironveil obfuscator source code if you want it: https://github.com/memcpython/ironveil

## how it works
1. first it reads the script to find the keys and encrypted strings
2. then it decrypts the bytecode using xor and decompresses it
3. then it translates the custom ironveil bytecode back to normal lua
4. finally it cleans and beautifies the code so you can read it easily

## requirements
- you need node.js installed on your pc

## how to install
go to the deobfuscator folder and run:
```bash
cd deobfuscator
npm install
```

## how to run
```bash
node index.js input.lua output.lua
```

## support / pull requests
if you want to help or improve the deobfuscator, you can open a pull request and i might accept it.

to support me, join my discord: discord.gg/qteAQmfJmP

## license
MIT
