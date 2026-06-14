# Worked-example numeric checks (done before drafting)

## Power of a Point
- Chord-chord: AB, CD meet at P. PA*PB = PC*PD. With PA=8, PB=6 => 48.
  CD=16, PC+PD=16, PC*PD=48 => x^2-16x+48=0 => x=4 or 12. PC=4, PD=12. OK.
- Tangent-secant: PT^2 = PA*PB. PT=6 => 36 = PA*PB. PA=4 => PB=9 => AB=5. OK.

## Mass points
Triangle ABC. D on BC with BD:DC=3:1. E on AC with AE:EC=2:3. AD meets BE at P.
- From BE (E on AC, AE:EC=2:3): mA:mC = 3:2.
- From AD (D on BC, BD:DC=3:1): mB:mC = 1:3.
- Set mC=6 => mA=9, mB=2.
- D mass = mB+mC = 8; BD:DC = mC:mB = 6:2 = 3:1 OK.
- E mass = mA+mC = 15; AE:EC = mC:mA = 6:9 = 2:3 OK.
- AP:PD = mD:mA = 8:9.
- BP:PE = mE:mB = 15:2.

## Ptolemy (regular pentagon diagonal)
Pentagon ABCDE, quad ABCD: AB=BC=CD=s, DA=d, AC=d, BD=d.
Ptolemy AC*BD = AB*CD + BC*DA => d^2 = s^2 + s*d => d^2 - s*d - s^2 = 0
=> d = s(1+sqrt5)/2 = phi * s. OK (golden ratio).

## Fact 5 / Incenter-Excenter Lemma (angle chase)
A=2a, B=2b, C=2c, a+b+c=90. AI meets circumcircle again at M (arc-BC midpoint).
angle MBI = angle MBC + angle CBI = a + b (MBC = MAC = a; CBI = b).
angle MIB = exterior angle of triangle ABI at I = angle IAB + angle ABI = a + b.
=> MB = MI; symmetric => MC = MI. So MB = MC = MI. OK.

All examples verified correct.
